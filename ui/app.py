"""
Prodapt AI Operations Center - Streamlit UI.

Run from the project root (after the DB is built and both ADK services are
started):
    streamlit run ui/app.py

This is the single entry point for staff/demo evaluators. It makes the
multi-agent orchestration visible: which workers ran, what each specialist
found, and the final CrewAI-polished customer response.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import streamlit as st

from config import (
    AGENT_CARD_PATH,
    BILLING_RESOLUTION_AGENT_URL,
    DB_PATH,
    NETWORK_DIAGNOSTICS_AGENT_URL,
    VECTOR_INDEX_DIR,
)
from orchestration.graph import run_telecom_assistant
from ui.db_explorer import render_audit_log, render_database_explorer

st.set_page_config(page_title="Prodapt AI Operations Center", page_icon="📡", layout="wide")


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------
def _db_ready() -> bool:
    return DB_PATH.exists()


def _vector_index_ready() -> bool:
    return VECTOR_INDEX_DIR.exists() and any(VECTOR_INDEX_DIR.iterdir())


def _adk_service_running(agent_url: str) -> bool:
    try:
        resp = httpx.get(f"{agent_url}{AGENT_CARD_PATH}", timeout=1.5)
        return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Sidebar - system status & framework map (spec 6.8.2)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("System status")

    if _db_ready():
        st.success("Database: Ready (data/telecom_ops.db)")
    else:
        st.error("Database: Not found - run `python init_db.py`")

    if _vector_index_ready():
        st.success("Vector index: Built (data/vector_index/)")
    else:
        st.info("Vector index: Not built yet - first PolicyRAG query will build it")

    net_up = _adk_service_running(NETWORK_DIAGNOSTICS_AGENT_URL)
    bill_up = _adk_service_running(BILLING_RESOLUTION_AGENT_URL)

    if net_up:
        st.success("Network Diagnostics ADK (8001): Running")
    else:
        st.error("Network Diagnostics ADK (8001): Not running")

    if bill_up:
        st.success("Billing Resolution ADK (8002): Running")
    else:
        st.error("Billing Resolution ADK (8002): Not running")

    if not (net_up and bill_up):
        st.warning(
            "One or more ADK services are down. Start them in separate terminals "
            "from the project root:\n\n"
            "```\npython adk-services/network_diagnostics/agent.py\n"
            "python adk-services/billing_resolution/agent.py\n```"
        )

    st.divider()
    st.header("Framework map")
    st.table(
        {
            "Capability": [
                "Policy & FAQ",
                "Network analytics",
                "Network diagnostics",
                "Billing resolution",
                "Orchestration",
                "Final customer comms",
            ],
            "Framework": [
                "LlamaIndex RAG",
                "LlamaIndex Semantic SQL",
                "Google ADK (A2A)",
                "Google ADK (A2A)",
                "LangGraph",
                "CrewAI",
            ],
        }
    )

# ---------------------------------------------------------------------------
# Main area (spec 6.8.1 / 6.8.3)
# ---------------------------------------------------------------------------
st.title("📡 Prodapt AI Operations Center")
st.caption(
    "Multi-agent telecom assistant built with LangGraph, LlamaIndex, Google ADK (A2A), and CrewAI."
)

def render_assistant() -> None:
    if "last_result" not in st.session_state:
        st.session_state.last_result = None

    user_query = st.text_area(
        "Customer inquiry",
        height=120,
        placeholder=(
            "Type or paste a plain-English inquiry, e.g. \"Customer CUST-10002 was "
            "charged twice for Unlimited Plus. Investigate and apply credit.\""
        ),
    )

    submitted = st.button("Submit", type="primary")

    if submitted:
        if not user_query.strip():
            st.warning("Enter an inquiry before submitting.")
        else:
            with st.spinner("Running the LangGraph supervisor and specialist workers..."):
                try:
                    st.session_state.last_result = run_telecom_assistant(user_query.strip())
                except Exception as exc:
                    st.session_state.last_result = {"error": str(exc)}

    result = st.session_state.last_result

    if result is not None:
        if result.get("error"):
            st.error(f"The assistant hit an error: {result['error']}")
        else:
            st.subheader("Response to customer")
            st.success(result.get("final_response") or "(No final response was produced.)")
            if result.get("audit_id"):
                st.caption(f"Saved to audit log as `{result['audit_id']}`")

            trace = result.get("execution_trace") or []
            with st.expander(f"🔎 Agent Execution Trace ({len(trace)} step(s))", expanded=True):
                if not trace:
                    st.info("No workers ran for this inquiry.")
                else:
                    for i, step in enumerate(trace, start=1):
                        st.markdown(f"**Step {i} — {step.get('worker', 'Unknown')}**")
                        st.text(step.get("output", ""))
                        if i < len(trace):
                            st.markdown("---")

            with st.expander("🛠️ Raw agent_context (debug)", expanded=False):
                st.text(result.get("agent_context") or "(empty)")
    else:
        st.info("Enter an inquiry above and click Submit to see the assistant in action.")


tab_assistant, tab_audit, tab_db = st.tabs(["💬 Assistant", "🧾 Audit Log", "🗄️ Database Explorer"])
with tab_assistant:
    render_assistant()
with tab_audit:
    render_audit_log()
with tab_db:
    render_database_explorer()
