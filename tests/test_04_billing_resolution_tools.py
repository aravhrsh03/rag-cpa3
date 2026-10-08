"""
Stage 4: Billing Resolution ADK tools (adk-services/billing_resolution/agent.py).

Exercises the $50 auto-approval rule directly against a seeded database -
no LLM call needed, since these are plain async, SQL-backed functions.

Skips cleanly if google-adk isn't installed yet.

    pytest tests/test_04_billing_resolution_tools.py -v
"""
import asyncio


def test_lookup_billing_account_known_customer(seeded_db, billing_resolution_module):
    result = asyncio.run(billing_resolution_module.lookup_billing_account("CUST-10002"))
    assert "error" not in result
    assert result["account"]["current_balance"] == result["open_charges_total"]


def test_lookup_billing_account_unknown_customer(seeded_db, billing_resolution_module):
    result = asyncio.run(billing_resolution_module.lookup_billing_account("CUST-99999"))
    assert "error" in result


def test_check_duplicate_charges_finds_cust10002_duplicate(seeded_db, billing_resolution_module):
    # Seed scenario: CUST-10002 has one open, flagged duplicate Unlimited
    # Plus charge, CHG-50022 (sql/02_seed_data.sql).
    result = asyncio.run(billing_resolution_module.check_duplicate_charges("CUST-10002"))
    assert result["has_open_duplicate"] is True
    assert any(c["charge_id"] == "CHG-50022" for c in result["duplicate_charges"])


def test_apply_billing_credit_auto_approves_under_limit(seeded_db, billing_resolution_module):
    before = asyncio.run(billing_resolution_module.lookup_billing_account("CUST-10002"))
    starting_balance = before["account"]["current_balance"]

    result = asyncio.run(
        billing_resolution_module.apply_billing_credit(
            "CUST-10002", 40.00, "test: duplicate charge credit", related_charge_id="CHG-50022"
        )
    )
    assert result["status"] == "APPLIED"
    assert result["current_balance"] == round(starting_balance - 40.00, 2)


def test_apply_billing_credit_holds_over_limit_for_approval(seeded_db, billing_resolution_module):
    before = asyncio.run(billing_resolution_module.lookup_billing_account("CUST-10002"))
    starting_balance = before["account"]["current_balance"]

    result = asyncio.run(
        billing_resolution_module.apply_billing_credit("CUST-10002", 65.99, "test: over-limit credit")
    )
    assert result["status"] == "PENDING_APPROVAL"
    assert result["current_balance"] == starting_balance


def test_apply_billing_credit_rejects_non_positive_amount(seeded_db, billing_resolution_module):
    result = asyncio.run(billing_resolution_module.apply_billing_credit("CUST-10002", 0, "bad amount"))
    assert "error" in result
