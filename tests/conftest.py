"""
Shared pytest fixtures for the Prodapt AI Operations Center test suite.

The test files are numbered in build/dependency order (config -> database ->
individual workers -> orchestration) so they can be run one at a time while
working through the stack, e.g.:

    pytest tests/test_01_config.py -v
    pytest tests/test_02_database.py -v
    ...
    pytest tests/ -v   # everything
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from config import PROJECT_ROOT, SCHEMA_SQL_PATH, SEED_SQL_PATH


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """Builds a throwaway telecom_ops.db from the real sql/01_schema.sql +
    sql/02_seed_data.sql and points common.db at it, so tests exercise the
    real schema and seed scenarios without touching data/telecom_ops.db."""
    db_path: Path = tmp_path / "test_telecom_ops.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_SQL_PATH.read_text(encoding="utf-8"))
        conn.executescript(SEED_SQL_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()

    import common.db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    return db_path


def _load_module_from_path(name: str, path: Path):
    """adk-services/* can't be imported with a normal dotted import (the
    directory name has a hyphen), so load each agent.py straight from its
    file path instead - same module objects notebooks-style tooling use."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def network_diagnostics_module():
    pytest.importorskip("google.adk", reason="google-adk is not installed yet")
    path = PROJECT_ROOT / "adk-services" / "network_diagnostics" / "agent.py"
    return _load_module_from_path("network_diagnostics_agent", path)


@pytest.fixture(scope="session")
def billing_resolution_module():
    pytest.importorskip("google.adk", reason="google-adk is not installed yet")
    path = PROJECT_ROOT / "adk-services" / "billing_resolution" / "agent.py"
    return _load_module_from_path("billing_resolution_agent", path)
