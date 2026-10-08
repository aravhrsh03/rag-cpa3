"""
Shared LangGraph state for the Prodapt AI Operations Center supervisor graph.
"""
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage

#: Worker node names, exactly as they must appear in the Streamlit execution
#: trace (section 6.8.3 of the spec).
WORKERS = [
    "PolicyRAG",
    "NetworkAnalytics",
    "NetworkDiagnosticsADK",
    "BillingResolutionADK",
    "CustomerCommsCrew",
]
ROUTE_OPTIONS = WORKERS + ["FINISH"]

#: Safety valve - if the supervisor hasn't reached CustomerCommsCrew/FINISH
#: within this many worker hops, graph.py forces CustomerCommsCrew then FINISH.
MAX_WORKER_HOPS = 6


class AgentState(TypedDict):
    """
    messages       - append-only conversation history across nodes.
    next           - supervisor's routing decision (a worker name or "FINISH").
    user_query     - the original customer/staff inquiry, unchanged for the whole run.
    agent_context  - accumulated plain-text findings from every worker so far,
                     passed to CustomerCommsCrew as its source material.
    execution_trace- one {"worker": ..., "output": ...} dict per worker call, in order;
                     rendered directly by the Streamlit Agent Execution Trace panel.
    final_response - the CrewAI-polished customer-facing text (set by CustomerCommsCrew).
    hops           - count of worker nodes executed so far, used to prevent infinite loops.
    """

    messages: Annotated[list[BaseMessage], operator.add]
    next: str
    user_query: str
    agent_context: str
    execution_trace: Annotated[list[dict[str, Any]], operator.add]
    final_response: str
    hops: int
