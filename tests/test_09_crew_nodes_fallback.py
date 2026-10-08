"""
Stage 9: CrewAI customer communications fallback path (orchestration/crew_nodes.py).

Exercises generate_customer_response's error handling when the crew itself
fails (e.g. no LLM key configured). The real two-agent crew needs a live LLM
call and is covered by the manual walkthrough in HOW_TO_RUN.md, not this
automated suite.

    pytest tests/test_09_crew_nodes_fallback.py -v
"""
from orchestration import crew_nodes


def test_generate_customer_response_falls_back_on_crew_failure(monkeypatch):
    def _boom(user_query, agent_context):
        raise RuntimeError("no LLM key configured")

    monkeypatch.setattr(crew_nodes, "_build_crew", _boom)

    result = crew_nodes.generate_customer_response(
        "Why was I charged twice?", "[BillingResolutionADK]\nFound duplicate charge CHG-50022."
    )
    assert "CustomerCommsCrew failed" in result
    assert "CHG-50022" in result
