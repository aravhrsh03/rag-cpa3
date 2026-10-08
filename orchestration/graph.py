"""
LangGraph supervisor + worker graph for the Prodapt AI Operations Center.

The supervisor is an LLM with structured output that reads the inquiry and
the findings gathered so far, then picks the next worker (or FINISH). Every
worker node calls exactly one underlying framework:

    PolicyRAG              -> llamaindex_rag.document_rag        (LlamaIndex RAG)
    NetworkAnalytics        -> llamaindex_rag.sql_semantic_search (LlamaIndex semantic SQL)
    NetworkDiagnosticsADK   -> orchestration.adk_remote_client    (Google ADK via A2A)
    BillingResolutionADK    -> orchestration.adk_remote_client    (Google ADK via A2A)
    CustomerCommsCrew       -> orchestration.crew_nodes           (CrewAI)

and returns to the supervisor, which loops until it routes to
CustomerCommsCrew (mandatory, last) and then FINISH.

`run_telecom_assistant(user_query)` is the single entry point the Streamlit
UI calls; it returns a dict matching the UI's data contract
(final_response / execution_trace / agent_context).
"""
import sys
import time
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from config import get_chat_llm
from llamaindex_rag.document_rag import answer_policy_question
from llamaindex_rag.sql_semantic_search import answer_network_analytics_question
from orchestration.adk_remote_client import diagnose_network_issue, resolve_billing_issue
from orchestration.crew_nodes import generate_customer_response
from common.audit import record_call
from orchestration.state import MAX_WORKER_HOPS, WORKERS, AgentState

TRACE_TRUNCATE_CHARS = 500


class RouteDecision(BaseModel):
    next: Literal[
        "PolicyRAG",
        "NetworkAnalytics",
        "NetworkDiagnosticsADK",
        "BillingResolutionADK",
        "CustomerCommsCrew",
        "FINISH",
    ] = Field(description="The next worker to run, or FINISH once the final response is ready.")
    reasoning: str = Field(description="One short sentence explaining the routing choice.")


_SUPERVISOR_SYSTEM_PROMPT = """You are the LangGraph supervisor for Prodapt's AI Operations Center, a US \
telecom provider. You read a customer/staff inquiry and decide which ONE \
specialist worker should run next. You never answer the inquiry yourself.

Workers available:
- PolicyRAG: answers policy/FAQ questions from documents - roaming zones and \
rates, SLA credit eligibility rules, billing dispute policy text, outage \
classification definitions, 5G FAQ, device upgrade/trade-in policy. Use for \
keywords like policy, roaming, SLA, 5G FAQ, upgrade, trade-in, rules, or \
"what does ... cost".
- NetworkAnalytics: answers analytics/aggregation questions from SQL - outage \
counts/severity by region, packet loss / latency / throughput rankings across \
towers, tower inventory, subscription analytics. Use for keywords like outage \
trends, packet loss, latency, "how many", "top N", "which region", "which \
towers".
- NetworkDiagnosticsADK: diagnoses a SPECIFIC tower or a live connectivity \
symptom (signal drops, "not working", a named tower ID, "diagnose"). Use when \
the question is about one tower's/one customer's live connectivity problem, \
not a regional analytics rollup.
- BillingResolutionADK: investigates a SPECIFIC customer's billing dispute \
(charged twice, credit, dispute, a CUST- id) and applies credits per policy.
- CustomerCommsCrew: drafts and reviews the final customer-facing response. \
This MUST be the last worker used for every customer-facing inquiry - route \
here once enough data/diagnosis/policy findings have been gathered, before \
FINISH.

Routing rules:
- Combined questions (e.g. outage duration + SLA credit eligibility, or \
billing + policy) need more than one data/policy worker BEFORE \
CustomerCommsCrew - e.g. NetworkAnalytics for the outage facts, then \
PolicyRAG for the credit rule, then CustomerCommsCrew.
- Do not route to a worker that has already run this turn (see the list \
below), except CustomerCommsCrew, which always runs exactly once, last.
- Only choose FINISH after CustomerCommsCrew has already produced the final \
response.

Inquiry:
{user_query}

Specialist findings gathered so far:
{agent_context}

Workers already run this turn: {completed_workers}

Decide the single next worker to run now (or FINISH)."""

_supervisor_llm = None


def _get_supervisor_llm():
    global _supervisor_llm
    if _supervisor_llm is None:
        base_llm = get_chat_llm(temperature=0)
        _supervisor_llm = base_llm.with_structured_output(RouteDecision)
    return _supervisor_llm


def supervisor_node(state: AgentState) -> dict:
    completed_workers = [t["worker"] for t in state["execution_trace"]]
    hops = state.get("hops", 0)

    # Safety valve against infinite loops / a misbehaving LLM.
    if hops >= MAX_WORKER_HOPS:
        forced_next = "FINISH" if "CustomerCommsCrew" in completed_workers else "CustomerCommsCrew"
        return {
            "next": forced_next,
            "messages": [AIMessage(content=f"Supervisor (hop limit reached) routing to {forced_next}.")],
        }

    system_message = SystemMessage(
        content=_SUPERVISOR_SYSTEM_PROMPT.format(
            user_query=state["user_query"],
            agent_context=state["agent_context"] or "(none yet)",
            completed_workers=", ".join(completed_workers) or "(none yet)",
        )
    )

    llm = _get_supervisor_llm()
    decision: RouteDecision = llm.invoke([system_message, HumanMessage(content="Decide the next step now.")])
    next_worker = decision.next

    # Hard rules that don't depend on the LLM getting it right, per spec 6.7/9.6:
    if next_worker == "FINISH" and "CustomerCommsCrew" not in completed_workers:
        next_worker = "CustomerCommsCrew"
    if next_worker == "CustomerCommsCrew" and "CustomerCommsCrew" in completed_workers:
        next_worker = "FINISH"
    if next_worker in completed_workers and next_worker != "CustomerCommsCrew" and next_worker != "FINISH":
        # Already-run data/policy worker picked again - treat as done, go to comms.
        next_worker = "CustomerCommsCrew"

    return {
        "next": next_worker,
        "messages": [AIMessage(content=f"Supervisor routing to {next_worker}. {decision.reasoning}")],
    }


def _record_worker_output(state: AgentState, worker: str, output: str) -> dict:
    output = output or "(no output returned)"
    prior_context = state["agent_context"]
    separator = "\n\n" if prior_context else ""
    new_context = f"{prior_context}{separator}[{worker}]\n{output}"

    return {
        "agent_context": new_context,
        "execution_trace": [{"worker": worker, "output": output[:TRACE_TRUNCATE_CHARS]}],
        "messages": [AIMessage(content=f"{worker} output: {output[:TRACE_TRUNCATE_CHARS]}")],
        "hops": state.get("hops", 0) + 1,
    }


def policy_rag_node(state: AgentState) -> dict:
    output = answer_policy_question(state["user_query"])
    return _record_worker_output(state, "PolicyRAG", output)


def network_analytics_node(state: AgentState) -> dict:
    output = answer_network_analytics_question(state["user_query"])
    return _record_worker_output(state, "NetworkAnalytics", output)


def network_diagnostics_adk_node(state: AgentState) -> dict:
    output = diagnose_network_issue(state["user_query"])
    return _record_worker_output(state, "NetworkDiagnosticsADK", output)


def billing_resolution_adk_node(state: AgentState) -> dict:
    output = resolve_billing_issue(state["user_query"])
    return _record_worker_output(state, "BillingResolutionADK", output)


def customer_comms_crew_node(state: AgentState) -> dict:
    output = generate_customer_response(state["user_query"], state["agent_context"])
    update = _record_worker_output(state, "CustomerCommsCrew", output)
    update["final_response"] = output
    return update


def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("PolicyRAG", policy_rag_node)
    builder.add_node("NetworkAnalytics", network_analytics_node)
    builder.add_node("NetworkDiagnosticsADK", network_diagnostics_adk_node)
    builder.add_node("BillingResolutionADK", billing_resolution_adk_node)
    builder.add_node("CustomerCommsCrew", customer_comms_crew_node)

    builder.set_entry_point("supervisor")

    for worker in WORKERS:
        builder.add_edge(worker, "supervisor")

    builder.add_conditional_edges(
        "supervisor",
        lambda state: state["next"],
        {**{w: w for w in WORKERS}, "FINISH": END},
    )

    return builder.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_telecom_assistant(user_query: str) -> dict:
    """
    Entry point for the Streamlit UI (and CLI testing). Runs the full
    supervisor graph for one inquiry and returns a UI-friendly dict:
        {"final_response": str, "execution_trace": [ {worker, output}, ... ],
         "agent_context": str, "error": str (only present on failure)}
    """
    initial_state: AgentState = {
        "messages": [HumanMessage(content=user_query)],
        "next": "",
        "user_query": user_query,
        "agent_context": "",
        "execution_trace": [],
        "final_response": "",
        "hops": 0,
    }

    started = time.perf_counter()
    try:
        result = get_graph().invoke(initial_state, config={"recursion_limit": 40})
    except Exception as exc:  # pragma: no cover - surfaced via st.error in the UI
        response = {"final_response": "", "execution_trace": [], "agent_context": "", "error": str(exc)}
    else:
        response = {
            "final_response": result.get("final_response", ""),
            "execution_trace": result.get("execution_trace", []),
            "agent_context": result.get("agent_context", ""),
        }

    # Persist every call (success or failure). Audit problems must never break
    # the assistant, so record_call() swallows its own errors.
    response["audit_id"] = record_call(
        user_query=user_query,
        response=response,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return response


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or "What is Prodapt's roaming policy for Western Europe?"
    result = run_telecom_assistant(query)
    print("=== Execution trace ===")
    for i, step in enumerate(result["execution_trace"], start=1):
        print(f"Step {i} - {step['worker']}:\n{step['output']}\n")
    if result.get("error"):
        print("ERROR:", result["error"])
    else:
        print("=== Final response ===")
        print(result["final_response"])
