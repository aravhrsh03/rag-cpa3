"""
CrewAI Customer Communications crew (CustomerCommsCrew worker).

A two-agent sequential crew: a Communications Specialist drafts a
customer-facing response from the original query plus every upstream
worker's accumulated findings (agent_context), and a Quality Reviewer
checks tone/accuracy/policy compliance and outputs only the final text.

Exposes one function - generate_customer_response - for the LangGraph node
to call.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crewai import Agent, Crew, Process, Task

from config import ANTHROPIC_API_KEY, OPENAI_API_KEY, get_crewai_model_string

# CrewAI (via LiteLLM) picks up provider API keys from the environment;
# config.py already loads .env, we just make sure whichever one is set is
# visible before crewai touches litellm.
import os

if OPENAI_API_KEY:
    os.environ.setdefault("OPENAI_API_KEY", OPENAI_API_KEY)
if ANTHROPIC_API_KEY:
    os.environ.setdefault("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)

_LLM_MODEL = get_crewai_model_string()


def _build_crew(user_query: str, agent_context: str) -> Crew:
    communications_specialist = Agent(
        role="Communications Specialist",
        goal=(
            "Draft an accurate, empathetic, easy-to-read response to the customer's "
            "inquiry, grounded strictly in the specialist findings provided - never "
            "invent facts, prices, or account details."
        ),
        backstory=(
            "You are a senior Prodapt customer communications writer. You turn "
            "technical findings from network, billing, and policy specialists into "
            "a response a customer can actually understand."
        ),
        llm=_LLM_MODEL,
        verbose=False,
        allow_delegation=False,
    )

    quality_reviewer = Agent(
        role="Quality Reviewer",
        goal=(
            "Review the draft for factual accuracy against the specialist findings, "
            "empathetic and professional tone, and policy compliance, then output "
            "only the final customer-ready text."
        ),
        backstory=(
            "You are a Prodapt QA reviewer for customer communications. You catch "
            "overpromises (e.g. claiming a credit was applied when it is only "
            "pending approval), unclear language, and tone problems before a "
            "message reaches a customer."
        ),
        llm=_LLM_MODEL,
        verbose=False,
        allow_delegation=False,
    )

    draft_task = Task(
        description=(
            f"Customer inquiry:\n{user_query}\n\n"
            f"Specialist findings gathered so far (from PolicyRAG / NetworkAnalytics / "
            f"NetworkDiagnosticsADK / BillingResolutionADK as applicable):\n"
            f"{agent_context or '(no upstream specialist output was provided)'}\n\n"
            "Write a draft response directly to the customer. Ground every claim "
            "(prices, eligibility, credit status, diagnosis) in the findings above. "
            "If a credit is PENDING_APPROVAL, say so plainly - do not say it has "
            "been applied. Keep it concise and professional."
        ),
        expected_output="A draft customer-facing response, in plain text.",
        agent=communications_specialist,
    )

    review_task = Task(
        description=(
            "Review the draft for: (1) factual accuracy against the specialist "
            "findings, (2) empathetic, professional tone, (3) compliance - never "
            "overstate what was actually approved. Fix any issues. "
            "Output ONLY the final customer-facing text - no headers, no notes, "
            "no explanation of your edits."
        ),
        expected_output="The final, polished customer-facing response text only.",
        agent=quality_reviewer,
        context=[draft_task],
    )

    return Crew(
        agents=[communications_specialist, quality_reviewer],
        tasks=[draft_task, review_task],
        process=Process.sequential,
        verbose=False,
    )


def generate_customer_response(user_query: str, agent_context: str) -> str:
    """
    Runs the two-agent sequential crew and returns the final, reviewer-approved
    customer-facing response text.
    """
    try:
        crew = _build_crew(user_query, agent_context)
        result = crew.kickoff()
        return str(result).strip()
    except Exception as exc:  # pragma: no cover - defensive, surfaced to UI
        return (
            "CustomerCommsCrew failed to generate a polished response "
            f"({exc}). Raw specialist findings:\n\n{agent_context}"
        )


if __name__ == "__main__":
    sample_query = "Customer CUST-10002 was charged twice for Unlimited Plus. Investigate and apply credit."
    sample_context = (
        "[BillingResolutionADK]\nFound duplicate Unlimited Plus charge CHG-50022 "
        "for $65.99. Credit inserted as PENDING_APPROVAL because it exceeds the "
        "$50.00 auto-approval limit. Balance remains $131.98."
    )
    print(generate_customer_response(sample_query, sample_context))
