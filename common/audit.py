"""
Persistent audit log: one row per call to run_telecom_assistant().

Stored in its own SQLite file (config.AUDIT_DB_PATH) so that resetting the
demo data with `python init_db.py` never erases the history of past calls.
Each row captures the inquiry, which workers ran (in order), the full
untruncated execution trace, the final reply, the outcome, timing, and which
LLM provider/model was configured.

record_call() never raises: an audit failure must not break the assistant.
"""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id        TEXT PRIMARY KEY,
    created_at_utc  TEXT NOT NULL,
    user_query      TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('SUCCESS', 'ERROR')),
    workers_called  TEXT NOT NULL,          -- e.g. 'BillingResolutionADK > CustomerCommsCrew'
    step_count      INTEGER NOT NULL,
    execution_trace TEXT NOT NULL,          -- JSON list of {worker, output}
    agent_context   TEXT,
    final_response  TEXT,
    error_message   TEXT,
    duration_ms     INTEGER NOT NULL,
    llm_provider    TEXT,
    llm_model       TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log (created_at_utc DESC);
"""


@contextmanager
def _connect():
    config.AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.AUDIT_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
    finally:
        conn.close()


def _model_name() -> str:
    return config.OPENAI_MODEL if config.LLM_PROVIDER == "openai" else config.ANTHROPIC_MODEL


def record_call(user_query: str, response: dict, duration_ms: int) -> Optional[str]:
    """Persist one assistant call. Returns the audit_id, or None if logging failed."""
    try:
        trace = response.get("execution_trace") or []
        error = response.get("error")
        audit_id = uuid.uuid4().hex[:12]
        with _connect() as conn:
            conn.execute(
                """INSERT INTO audit_log (audit_id, created_at_utc, user_query, status,
                       workers_called, step_count, execution_trace, agent_context,
                       final_response, error_message, duration_ms, llm_provider, llm_model)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    audit_id,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    user_query,
                    "ERROR" if error else "SUCCESS",
                    " > ".join(step.get("worker", "?") for step in trace),
                    len(trace),
                    json.dumps(trace, ensure_ascii=False),
                    response.get("agent_context", ""),
                    response.get("final_response", ""),
                    error,
                    duration_ms,
                    config.LLM_PROVIDER,
                    _model_name(),
                ),
            )
            conn.commit()
        return audit_id
    except Exception:  # pragma: no cover - audit must never break the caller
        return None


def list_calls(limit: int = 200) -> list[dict]:
    """Most recent calls first (without the bulky trace/context columns)."""
    if not config.AUDIT_DB_PATH.exists():
        return []
    with _connect() as conn:
        rows = conn.execute(
            """SELECT audit_id, created_at_utc, user_query, status, workers_called,
                      step_count, duration_ms, llm_provider, llm_model
               FROM audit_log ORDER BY created_at_utc DESC, rowid DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_call(audit_id: str) -> Optional[dict]:
    """Full record for one call, with execution_trace decoded from JSON."""
    if not config.AUDIT_DB_PATH.exists():
        return None
    with _connect() as conn:
        row = conn.execute("SELECT * FROM audit_log WHERE audit_id = ?", (audit_id,)).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["execution_trace"] = json.loads(record["execution_trace"] or "[]")
    return record
