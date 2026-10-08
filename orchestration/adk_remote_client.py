"""
LangGraph <-> Google ADK A2A bridge.

For each ADK service (Network Diagnostics on :8001, Billing Resolution on
:8002) this module:
  1. Points a RemoteA2aAgent at the service's published agent card.
  2. Wraps it in a lightweight local proxy ADK Agent whose only job is to
     transfer the incoming message straight to that remote sub_agent.
  3. Runs the proxy through an ADK Runner (with an in-memory session) and
     collects the final response text.
  4. Exposes plain synchronous functions - diagnose_network_issue() and
     resolve_billing_issue() - that LangGraph worker nodes call directly.

If a service's port isn't up, callers get a clear, actionable string back
instead of a stack trace, so the graph can keep running and the Streamlit UI
can show something useful.
"""
import asyncio
import sys
import threading
import uuid
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from config import (
    AGENT_CARD_PATH,
    BILLING_RESOLUTION_AGENT_URL,
    NETWORK_DIAGNOSTICS_AGENT_URL,
    get_adk_model,
)

_APP_NAME = "prodapt_ops_center"


def _run_coro_blocking(coro_factory: Callable[[], "asyncio.Future"]):
    """Runs an async coroutine to completion from sync code, even if (unusually)
    called from inside an already-running event loop (e.g. some Streamlit /
    notebook setups) by falling back to a dedicated thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    result: dict = {}

    def _target():
        result["value"] = asyncio.run(coro_factory())

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    return result["value"]


def _service_reachable(agent_url: str, timeout: float = 2.0) -> bool:
    try:
        resp = httpx.get(f"{agent_url}{AGENT_CARD_PATH}", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def _build_proxy_agent(name: str, agent_url: str, description: str) -> Agent:
    remote_agent = RemoteA2aAgent(
        name=f"{name}_remote",
        description=description,
        agent_card=f"{agent_url}{AGENT_CARD_PATH}",
    )
    return Agent(
        name=f"{name}_proxy",
        model=get_adk_model(),
        instruction=(
            f"You are a pure router with a single sub-agent named '{remote_agent.name}'. "
            "On every user message, immediately transfer to that sub-agent and let it "
            "handle the request. Never answer directly yourself."
        ),
        sub_agents=[remote_agent],
    )


async def _invoke_agent(agent: Agent, message_text: str) -> str:
    session_service = InMemorySessionService()
    user_id = "orchestrator"
    session_id = f"session-{uuid.uuid4().hex}"
    await session_service.create_session(app_name=_APP_NAME, user_id=user_id, session_id=session_id)

    runner = Runner(agent=agent, app_name=_APP_NAME, session_service=session_service)
    content = types.Content(role="user", parts=[types.Part(text=message_text)])

    final_chunks: list[str] = []
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(part.text for part in event.content.parts if getattr(part, "text", None))
            if text:
                final_chunks.append(text)

    return "\n".join(final_chunks).strip()


def _call_remote_worker(name: str, agent_url: str, description: str, start_cmd: str, message_text: str) -> str:
    if not _service_reachable(agent_url):
        return (
            f"{name} is not reachable at {agent_url}. Start it with:\n"
            f"    {start_cmd}\n"
            "then resubmit the inquiry."
        )

    proxy_agent = _build_proxy_agent(name, agent_url, description)
    try:
        return _run_coro_blocking(lambda: _invoke_agent(proxy_agent, message_text))
    except Exception as exc:  # pragma: no cover - defensive, surfaced to UI
        return (
            f"{name} call failed even though {agent_url} responded to a health check: {exc}\n"
            f"Confirm the service is fully started ({start_cmd}) and try again."
        )


def diagnose_network_issue(query: str) -> str:
    """Delegates a network/connectivity inquiry to the remote Network
    Diagnostics ADK agent (port 8001) and returns its findings as text."""
    return _call_remote_worker(
        name="NetworkDiagnosticsADK",
        agent_url=NETWORK_DIAGNOSTICS_AGENT_URL,
        description="Diagnoses live tower and connectivity issues from SQL data.",
        start_cmd="python adk-services/network_diagnostics/agent.py",
        message_text=query,
    )


def resolve_billing_issue(query: str) -> str:
    """Delegates a billing dispute inquiry to the remote Billing Resolution
    ADK agent (port 8002) and returns its findings/actions as text."""
    return _call_remote_worker(
        name="BillingResolutionADK",
        agent_url=BILLING_RESOLUTION_AGENT_URL,
        description="Investigates billing disputes and applies credits per policy.",
        start_cmd="python adk-services/billing_resolution/agent.py",
        message_text=query,
    )


if __name__ == "__main__":
    q = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
    if len(sys.argv) > 1 and sys.argv[1] == "billing":
        print(resolve_billing_issue(q or "Customer CUST-10002 was charged twice for Unlimited Plus."))
    else:
        print(diagnose_network_issue(q or "My 5G keeps dropping near tower TX-512 in Austin."))
