"""
Stage 5: shared LangGraph state (orchestration/state.py).

Pure data-shape checks - no LLM, no database, no network.

    pytest tests/test_05_orchestration_state.py -v
"""
from orchestration.state import MAX_WORKER_HOPS, ROUTE_OPTIONS, WORKERS, AgentState


def test_workers_list_matches_spec_order():
    assert WORKERS == [
        "PolicyRAG",
        "NetworkAnalytics",
        "NetworkDiagnosticsADK",
        "BillingResolutionADK",
        "CustomerCommsCrew",
    ]


def test_route_options_adds_finish():
    assert ROUTE_OPTIONS == WORKERS + ["FINISH"]


def test_max_worker_hops_is_a_positive_safety_valve():
    assert isinstance(MAX_WORKER_HOPS, int)
    assert MAX_WORKER_HOPS > 0


def test_agent_state_has_expected_fields():
    assert set(AgentState.__annotations__) == {
        "messages",
        "next",
        "user_query",
        "agent_context",
        "execution_trace",
        "final_response",
        "hops",
    }
