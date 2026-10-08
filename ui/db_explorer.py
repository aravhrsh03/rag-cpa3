"""
Database Explorer + Audit Log tabs for the Streamlit UI.

Everything here is READ-ONLY: databases are opened with SQLite's `mode=ro`
URI flag, and the ad-hoc SQL box only accepts a single SELECT/WITH statement.
"""
import json
import re
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from common import audit

MAX_ROWS = 500

# Plain-English meaning of each table, shown next to its schema.
TABLE_NOTES = {
    "network_towers": "The 10 cell towers: region, city, technology, current status.",
    "network_outages": "Historical outage log (severity, duration, root cause).",
    "tower_performance": "Time series of latency / packet loss / throughput / signal per tower.",
    "open_incidents": "Live NOC incident queue (read by Network Diagnostics).",
    "customer_subscriptions": "Customer plans, fees and account types.",
    "billing_accounts": "Current balance per customer (changed when a credit is APPLIED).",
    "billing_charges": "Line items, duplicate flags, OPEN / PAID status.",
    "billing_credits": "Credits: APPLIED (<= $50) or PENDING_APPROVAL (> $50).",
    "billing_disputes": "Dispute records (reference only).",
    "audit_log": "One row per assistant call: query, route, trace, reply, timing.",
}

# One-click views that answer "what is happening right now?"
QUICK_VIEWS = {
    "Pending credit approvals": (
        config.DB_PATH,
        "SELECT * FROM billing_credits WHERE status = 'PENDING_APPROVAL' ORDER BY 1 DESC",
    ),
    "Latest credits": (config.DB_PATH, "SELECT * FROM billing_credits ORDER BY 1 DESC LIMIT 20"),
    "Open incidents": (config.DB_PATH, "SELECT * FROM open_incidents"),
    "Towers not OPERATIONAL": (config.DB_PATH, "SELECT * FROM network_towers WHERE status <> 'OPERATIONAL'"),
    "Customers with a balance": (
        config.DB_PATH,
        "SELECT * FROM billing_accounts WHERE current_balance > 0 ORDER BY current_balance DESC LIMIT 20",
    ),
}


def _ro_connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _query_df(path: Path, sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = _ro_connect(path)
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchmany(MAX_ROWS)
        return pd.DataFrame([dict(r) for r in rows], columns=[d[0] for d in cur.description])
    finally:
        conn.close()


def _tables(path: Path) -> list[str]:
    df = _query_df(path, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return df["name"].tolist()


def _safe_select(sql: str) -> str:
    cleaned = sql.strip().rstrip(";").strip()
    if ";" in cleaned:
        raise ValueError("Only one statement is allowed.")
    if not re.match(r"^(select|with)\b", cleaned, re.IGNORECASE):
        raise ValueError("Only SELECT / WITH queries are allowed here (read-only explorer).")
    return cleaned


def render_database_explorer() -> None:
    st.subheader("🗄️ Database Explorer")
    st.caption("Read-only view of the SQLite databases behind the agents. Nothing here can modify data.")

    sources = {"telecom_ops.db (business data)": config.DB_PATH, "audit_log.db (call history)": config.AUDIT_DB_PATH}
    available = {label: p for label, p in sources.items() if p.exists()}
    if not available:
        st.error("No database found. Run `python init_db.py` from the project root.")
        return

    label = st.radio("Database", list(available), horizontal=True)
    path = available[label]
    tables = _tables(path)

    # --- Overview: every table with its row count ------------------------------
    overview = pd.DataFrame(
        [
            {
                "table": t,
                "rows": int(_query_df(path, f'SELECT COUNT(*) AS n FROM "{t}"')["n"][0]),
                "what it holds": TABLE_NOTES.get(t, ""),
            }
            for t in tables
        ]
    )
    st.markdown("**Tables**")
    st.dataframe(overview, hide_index=True, width="stretch")

    # --- Table detail ----------------------------------------------------------
    table = st.selectbox("Inspect a table", tables)
    left, right = st.columns([1, 2])
    with left:
        st.markdown("**Columns**")
        cols = _query_df(path, f'PRAGMA table_info("{table}")')[["name", "type", "notnull", "pk"]]
        st.dataframe(cols, hide_index=True, width="stretch")
        fks = _query_df(path, f'PRAGMA foreign_key_list("{table}")')
        if not fks.empty:
            st.markdown("**Foreign keys**")
            st.dataframe(fks[["from", "table", "to"]], hide_index=True, width="stretch")
    with right:
        st.markdown(f"**Data preview** (first {MAX_ROWS} rows max)")
        n = st.slider("Rows to show", 5, 200, 25, key="explorer_rows")
        st.dataframe(_query_df(path, f'SELECT * FROM "{table}" LIMIT ?', (n,)), hide_index=True, width="stretch")

    # --- Quick views (only for the business DB) --------------------------------
    if path == config.DB_PATH:
        st.divider()
        st.markdown("**What's happening right now**")
        choice = st.selectbox("Quick view", list(QUICK_VIEWS))
        view_path, view_sql = QUICK_VIEWS[choice]
        st.code(view_sql, language="sql")
        st.dataframe(_query_df(view_path, view_sql), hide_index=True, width="stretch")

    # --- Ad-hoc read-only SQL --------------------------------------------------
    st.divider()
    st.markdown("**Run your own SELECT** (read-only)")
    sql = st.text_area("SQL", value=f'SELECT * FROM "{table}" LIMIT 10', height=100, key=f"sql_{path.name}")
    if st.button("Run query", key="run_sql"):
        try:
            st.dataframe(_query_df(path, _safe_select(sql)), hide_index=True, width="stretch")
        except Exception as exc:
            st.error(str(exc))


def render_audit_log() -> None:
    st.subheader("🧾 Audit Log")
    st.caption("Every call to the assistant is saved to data/audit_log.db, including failures.")

    calls = audit.list_calls(limit=200)
    if not calls:
        st.info("No calls recorded yet. Submit an inquiry on the Assistant tab.")
        return

    df = pd.DataFrame(calls)
    ok = int((df["status"] == "SUCCESS").sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Calls logged", len(df))
    c2.metric("Successful", ok)
    c3.metric("Errors", len(df) - ok)
    c4.metric("Avg duration", f"{df['duration_ms'].mean() / 1000:.1f}s")

    status_filter = st.multiselect("Status", ["SUCCESS", "ERROR"], default=["SUCCESS", "ERROR"])
    shown = df[df["status"].isin(status_filter)]
    st.dataframe(
        shown[["audit_id", "created_at_utc", "status", "user_query", "workers_called", "duration_ms"]],
        hide_index=True,
        width="stretch",
    )

    if shown.empty:
        return
    chosen = st.selectbox("Open a call", shown["audit_id"].tolist())
    record = audit.get_call(chosen)
    if record is None:
        return
    st.markdown(f"**Inquiry:** {record['user_query']}")
    st.caption(
        f"{record['created_at_utc']} UTC · {record['duration_ms'] / 1000:.1f}s · "
        f"{record['llm_provider']} / {record['llm_model']} · {record['status']}"
    )
    if record["error_message"]:
        st.error(record["error_message"])
    if record["final_response"]:
        st.success(record["final_response"])
    with st.expander(f"Execution trace ({record['step_count']} step(s))", expanded=False):
        for i, step in enumerate(record["execution_trace"], start=1):
            st.markdown(f"**Step {i} — {step.get('worker', '?')}**")
            st.text(step.get("output", ""))
    st.download_button(
        "Download this record (JSON)",
        data=json.dumps(record, indent=2, ensure_ascii=False),
        file_name=f"audit_{chosen}.json",
        mime="application/json",
    )
