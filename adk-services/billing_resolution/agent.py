"""
Billing Resolution ADK service (A2A, port 8002).

Runs standalone:
    python adk-services/billing_resolution/agent.py

Exposes a Google ADK Agent with three SQL-backed async tools over the A2A
protocol. LangGraph never imports this module directly - it talks to it
over HTTP via orchestration/adk_remote_client.py, once this process is
running. The agent card is published at:
    http://localhost:8002/.well-known/agent-card.json

Every tool opens its own SQLite connection through common/db.py and reads/
writes billing_accounts, billing_charges, and billing_credits directly.
No balances, charges, or credits are ever kept in a Python dict - the
$50 auto-approval rule is enforced against the database on every call.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import Agent

from common.db import DatabaseNotInitializedError, execute_write, fetch_all, fetch_one
from config import BILLING_AUTO_APPROVAL_LIMIT, BILLING_RESOLUTION_PORT, get_adk_model


async def lookup_billing_account(customer_id: str) -> dict:
    """Look up a customer's billing account balance and their charges.

    Args:
        customer_id: Customer identifier, e.g. "CUST-10002".

    Returns:
        A dict with the account row (including current_balance), all OPEN
        charges (the current bill), a handful of the most recent PAID
        charges for context, and a computed open_charges_total that should
        match current_balance. Returns {"error": ...} if the customer_id
        does not exist.
    """
    def _run():
        account = fetch_one("SELECT * FROM billing_accounts WHERE customer_id = ?", (customer_id,))
        if account is None:
            return {"error": f"No billing account found for customer_id '{customer_id}'."}

        open_charges = fetch_all(
            "SELECT * FROM billing_charges WHERE customer_id = ? AND invoice_status = 'OPEN' "
            "ORDER BY charge_date",
            (customer_id,),
        )
        recent_paid_charges = fetch_all(
            "SELECT * FROM billing_charges WHERE customer_id = ? AND invoice_status = 'PAID' "
            "ORDER BY charge_date DESC LIMIT 6",
            (customer_id,),
        )
        open_charges_total = round(sum(c["amount"] for c in open_charges), 2)

        return {
            "account": account,
            "open_charges": open_charges,
            "recent_paid_charges": recent_paid_charges,
            "open_charges_total": open_charges_total,
            "note": (
                "current_balance should equal open_charges_total. PAID rows are "
                "prior billing cycles and are not part of the current balance."
            ),
        }

    try:
        return await asyncio.to_thread(_run)
    except DatabaseNotInitializedError as exc:
        return {"error": str(exc)}


async def check_duplicate_charges(customer_id: str) -> dict:
    """Find OPEN charges for a customer that look like duplicates.

    A charge counts as a duplicate when it is explicitly flagged
    (is_duplicate_flag = 1) OR it shares the same description and billing
    period as another OPEN charge for the same customer. The same plan name
    billed in a different month is NOT a duplicate. A charge that already
    has an APPLIED credit against it is excluded (do not re-credit it).

    Args:
        customer_id: Customer identifier, e.g. "CUST-10002".

    Returns:
        A dict with has_open_duplicate (bool) and a list of the duplicate
        charge rows still open and not yet credited. Returns {"error": ...}
        if the customer_id does not exist.
    """
    def _run():
        account = fetch_one("SELECT customer_id FROM billing_accounts WHERE customer_id = ?", (customer_id,))
        if account is None:
            return {"error": f"No billing account found for customer_id '{customer_id}'."}

        duplicates = fetch_all(
            """
            SELECT * FROM billing_charges
            WHERE customer_id = ? AND invoice_status = 'OPEN'
              AND (
                  is_duplicate_flag = 1
                  OR (description, billing_period) IN (
                      SELECT description, billing_period FROM billing_charges
                      WHERE customer_id = ? AND invoice_status = 'OPEN'
                      GROUP BY description, billing_period HAVING COUNT(*) > 1
                  )
              )
              AND charge_id NOT IN (
                  SELECT related_charge_id FROM billing_credits
                  WHERE status = 'APPLIED' AND related_charge_id IS NOT NULL
              )
            ORDER BY charge_date
            """,
            (customer_id, customer_id),
        )

        return {
            "customer_id": customer_id,
            "has_open_duplicate": len(duplicates) > 0,
            "duplicate_charges": duplicates,
        }

    try:
        return await asyncio.to_thread(_run)
    except DatabaseNotInitializedError as exc:
        return {"error": str(exc)}


async def apply_billing_credit(customer_id: str, amount: float, reason: str, related_charge_id: str | None = None) -> dict:
    """Apply (or queue for approval) a billing credit for a customer, per
    billing_disputes_policy.txt: amounts of $50.00 or less are auto-approved
    and immediately reduce the balance; amounts over $50.00 are stored as
    PENDING_APPROVAL and the balance is left unchanged until a supervisor
    approves it.

    Args:
        customer_id: Customer identifier, e.g. "CUST-10002".
        amount: The credit amount in USD. This is the amount of the specific
            duplicate/disputed line item, not the customer's whole balance.
        reason: A short explanation of why the credit is being issued,
            referencing the disputed charge.
        related_charge_id: Optional charge_id this credit relates to, e.g.
            "CHG-50022".

    Returns:
        A dict with the new billing_credits row, its status (APPLIED or
        PENDING_APPROVAL), and the account's balance after the operation.
        Returns {"error": ...} if the customer_id does not exist or amount
        is not positive.
    """
    def _run():
        account = fetch_one("SELECT * FROM billing_accounts WHERE customer_id = ?", (customer_id,))
        if account is None:
            return {"error": f"No billing account found for customer_id '{customer_id}'."}
        if amount is None or amount <= 0:
            return {"error": f"Credit amount must be a positive number, got {amount}."}

        rounded_amount = round(float(amount), 2)
        auto_approved = rounded_amount <= BILLING_AUTO_APPROVAL_LIMIT
        status = "APPLIED" if auto_approved else "PENDING_APPROVAL"

        # Per billing_disputes_policy.txt section 6: the balance must not go
        # below zero. If the credit would overshoot, apply only enough to
        # zero the balance out and note the clamp.
        balance_floor_note = ""
        actual_reduction = 0.0
        if auto_approved:
            actual_reduction = min(rounded_amount, account["current_balance"])
            if actual_reduction < rounded_amount:
                balance_floor_note = (
                    f" Balance was only {account['current_balance']:.2f}; credit was capped "
                    f"to {actual_reduction:.2f} so the balance would not go below zero."
                )

        credit_id = execute_write(
            """
            INSERT INTO billing_credits
                (customer_id, amount, reason, status, created_at, related_charge_id)
            VALUES (?, ?, ?, ?, datetime('now'), ?)
            """,
            (customer_id, rounded_amount, reason, status, related_charge_id),
        )

        if auto_approved and actual_reduction > 0:
            execute_write(
                """
                UPDATE billing_accounts
                SET current_balance = ROUND(current_balance - ?, 2), last_updated = datetime('now')
                WHERE customer_id = ?
                """,
                (actual_reduction, customer_id),
            )

        refreshed_account = fetch_one("SELECT * FROM billing_accounts WHERE customer_id = ?", (customer_id,))

        return {
            "credit_id": credit_id,
            "customer_id": customer_id,
            "amount": rounded_amount,
            "status": status,
            "auto_approval_limit": BILLING_AUTO_APPROVAL_LIMIT,
            "balance_changed": auto_approved and actual_reduction > 0,
            "current_balance": refreshed_account["current_balance"],
            "message": (
                f"Credit of ${rounded_amount:.2f} APPLIED; balance reduced to "
                f"${refreshed_account['current_balance']:.2f}.{balance_floor_note}"
                if auto_approved
                else f"Credit of ${rounded_amount:.2f} exceeds the ${BILLING_AUTO_APPROVAL_LIMIT:.2f} "
                     f"auto-approval limit and is PENDING_APPROVAL; balance remains "
                     f"${refreshed_account['current_balance']:.2f} until a supervisor approves it."
            ),
        }

    try:
        return await asyncio.to_thread(_run)
    except DatabaseNotInitializedError as exc:
        return {"error": str(exc)}


root_agent = Agent(
    name="billing_resolution_agent",
    model=get_adk_model(),
    description=(
        "Billing Resolution specialist. Investigates billing disputes using "
        "SQL-backed tools over billing_accounts, billing_charges, and "
        "billing_credits, and applies credits per policy."
    ),
    instruction=(
        "You are Prodapt's Billing Resolution specialist. You investigate "
        "billing disputes for customer support agents.\n\n"
        "Standard workflow for a dispute:\n"
        "1. Call lookup_billing_account to see the customer's balance and open charges.\n"
        "2. Call check_duplicate_charges to confirm whether a real duplicate exists.\n"
        "3. If a duplicate is confirmed and not already credited, call "
        "apply_billing_credit with the amount of the specific duplicate line item "
        f"(not the whole balance) and a clear reason citing the charge_id.\n\n"
        "Rules:\n"
        "- Never invent balances, charges, or credit outcomes - always use the tools.\n"
        "- A charge for the same plan/add-on in a different billing period is NOT a "
        "duplicate - only credit charges check_duplicate_charges actually returns.\n"
        "- Do not credit a charge that already has an APPLIED credit against it.\n"
        f"- Credits of ${BILLING_AUTO_APPROVAL_LIMIT:.2f} or less are auto-approved by "
        "the tool; credits above that are stored as PENDING_APPROVAL and the balance "
        "does not change - report the outcome exactly as the tool returns it, do not "
        "claim a credit was applied when the tool says PENDING_APPROVAL.\n"
        "- Write your findings as a concise technical summary of what you found and "
        "what action was taken/queued. Do not write the final customer-facing letter - "
        "that is handled by a separate communications specialist downstream."
    ),
    tools=[lookup_billing_account, check_duplicate_charges, apply_billing_credit],
)

a2a_app = to_a2a(root_agent, port=BILLING_RESOLUTION_PORT)

if __name__ == "__main__":
    import uvicorn

    print(f"Starting Billing Resolution ADK service on port {BILLING_RESOLUTION_PORT} ...")
    print(f"Agent card: http://localhost:{BILLING_RESOLUTION_PORT}/.well-known/agent-card.json")
    uvicorn.run(a2a_app, host="0.0.0.0", port=BILLING_RESOLUTION_PORT)
