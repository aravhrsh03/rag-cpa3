"""
Thin SQLite access helpers shared by the ADK agent tools and (indirectly)
documented for the LlamaIndex semantic SQL engine.

Per the project's database rules, NO business data (tower status, billing
balances, incidents, etc.) is ever cached in a Python dict/list/global. Every
call here opens a fresh connection, runs one statement against
data/telecom_ops.db, and returns plain dicts/rows - nothing is retained
between calls.
"""
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable, Optional

from config import DB_PATH


class DatabaseNotInitializedError(RuntimeError):
    pass


@contextmanager
def get_connection():
    if not DB_PATH.exists():
        raise DatabaseNotInitializedError(
            f"{DB_PATH} does not exist yet. Run `python init_db.py` from the "
            "project root first."
        )
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def fetch_all(query: str, params: Iterable[Any] = ()) -> list[dict]:
    with get_connection() as conn:
        cur = conn.execute(query, tuple(params))
        return [dict(row) for row in cur.fetchall()]


def fetch_one(query: str, params: Iterable[Any] = ()) -> Optional[dict]:
    rows = fetch_all(query, params)
    return rows[0] if rows else None


def execute_write(query: str, params: Iterable[Any] = ()) -> int:
    """Runs one INSERT/UPDATE/DELETE and returns lastrowid (0 for UPDATE/DELETE)."""
    with get_connection() as conn:
        cur = conn.execute(query, tuple(params))
        conn.commit()
        return cur.lastrowid or 0
