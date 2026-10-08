"""
Builds data/telecom_ops.db by running sql/01_schema.sql then sql/02_seed_data.sql.

Usage (from the project root):
    python init_db.py

Re-running this script re-creates the database from scratch (the schema
script drops every table first), which is intentional so the demo data can
be reset after applying credits during a walkthrough.
"""
import sqlite3
import sys

from config import DATA_DIR, DB_PATH, SCHEMA_SQL_PATH, SEED_SQL_PATH


def main() -> None:
    if not SCHEMA_SQL_PATH.exists() or not SEED_SQL_PATH.exists():
        print(f"ERROR: expected {SCHEMA_SQL_PATH} and {SEED_SQL_PATH} to exist.")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Building {DB_PATH} ...")
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.executescript(SCHEMA_SQL_PATH.read_text(encoding="utf-8"))
        conn.executescript(SEED_SQL_PATH.read_text(encoding="utf-8"))
        conn.commit()

        cur = conn.cursor()
        checks = [
            ("network_towers", "SELECT COUNT(*) FROM network_towers", 10),
            (
                "CUST-10002 open duplicate charges",
                "SELECT COUNT(*) FROM billing_charges "
                "WHERE customer_id='CUST-10002' AND is_duplicate_flag=1",
                1,
            ),
        ]
        print("\nVerification:")
        ok = True
        for label, query, expected in checks:
            cur.execute(query)
            actual = cur.fetchone()[0]
            status = "OK" if actual == expected else "MISMATCH"
            if actual != expected:
                ok = False
            print(f"  [{status}] {label}: {actual} (expected {expected})")

        for table in (
            "network_towers", "network_outages", "tower_performance",
            "open_incidents", "customer_subscriptions", "billing_accounts",
            "billing_charges", "billing_credits", "billing_disputes",
        ):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"  {table}: {cur.fetchone()[0]} rows")

        print(f"\n{'Database ready.' if ok else 'Database built with mismatches - check the SQL files.'}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
