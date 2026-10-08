"""
Stage 6: LangGraph <-> Google ADK bridge (orchestration/adk_remote_client.py).

Only exercises the "service isn't running" path, which needs no network
access and no API key. The real success path requires the ADK services to
actually be running on :8001/:8002 plus a configured LLM key - that's the
manual walkthrough in HOW_TO_RUN.md, not this automated suite.

    pytest tests/test_06_adk_remote_client.py -v
"""
from orchestration import adk_remote_client


def test_service_reachable_is_false_for_a_closed_port():
    assert adk_remote_client._service_reachable("http://localhost:9", timeout=1.0) is False


def test_diagnose_network_issue_reports_unreachable_service(monkeypatch):
    monkeypatch.setattr(adk_remote_client, "NETWORK_DIAGNOSTICS_AGENT_URL", "http://localhost:9")
    message = adk_remote_client.diagnose_network_issue("my 5G keeps dropping")
    assert "not reachable" in message
    assert "network_diagnostics/agent.py" in message


def test_resolve_billing_issue_reports_unreachable_service(monkeypatch):
    monkeypatch.setattr(adk_remote_client, "BILLING_RESOLUTION_AGENT_URL", "http://localhost:9")
    message = adk_remote_client.resolve_billing_issue("customer was charged twice")
    assert "not reachable" in message
    assert "billing_resolution/agent.py" in message
