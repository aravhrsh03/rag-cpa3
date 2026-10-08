"""
Stage 2: database layer (common/db.py, built from sql/01_schema.sql +
sql/02_seed_data.sql via init_db.py).

Run after test_01_config.py passes.

    pytest tests/test_02_database.py -v
"""
import pytest

from common.db import DatabaseNotInitializedError, execute_write, fetch_all, fetch_one


def test_fetch_all_returns_all_ten_seeded_towers(seeded_db):
    towers = fetch_all("SELECT * FROM network_towers")
    assert len(towers) == 10


def test_fetch_one_returns_known_tower(seeded_db):
    tower = fetch_one("SELECT * FROM network_towers WHERE tower_id = ?", ("TX-512",))
    assert tower["city"] == "Austin"
    assert tower["technology"] == "5G"
    assert tower["status"] == "OPERATIONAL"


def test_fetch_one_returns_none_for_missing_row(seeded_db):
    assert fetch_one("SELECT * FROM network_towers WHERE tower_id = ?", ("NOPE-000",)) is None


def test_execute_write_inserts_and_commits(seeded_db):
    new_id = execute_write(
        "INSERT INTO billing_credits (customer_id, amount, reason, status, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        ("CUST-10002", 10.0, "test credit", "APPLIED"),
    )
    assert new_id > 0

    row = fetch_one("SELECT * FROM billing_credits WHERE credit_id = ?", (new_id,))
    assert row["amount"] == 10.0
    assert row["status"] == "APPLIED"


def test_missing_database_raises_clear_error(tmp_path, monkeypatch):
    import common.db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "does_not_exist.db")
    with pytest.raises(DatabaseNotInitializedError):
        fetch_all("SELECT 1")
