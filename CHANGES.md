# Changes in this version

This repository is the Prodapt AI Operations Center from
[`claude-rag`](https://github.com/aravhrsh03/claude-rag) (LangGraph + LlamaIndex
+ Google ADK + CrewAI + Streamlit, running on Claude), with two additions:

1. a **persistent audit log** of every assistant call, and
2. a **Database Explorer** (plus an Audit Log viewer) in the Streamlit UI.

Everything else (the agents, the database schema, the policy documents, the
five demo scenarios) is unchanged.

## Summary of changes

| File | Change | Type |
|---|---|---|
| `common/audit.py` | Audit log module: creates the `audit_log` table, `record_call()`, `list_calls()`, `get_call()` | **New** |
| `ui/db_explorer.py` | `render_database_explorer()` and `render_audit_log()` for the two new tabs | **New** |
| `tests/test_10_audit_log.py` | 5 tests for the audit log | **New** |
| `config.py` | Added `AUDIT_DB_PATH` (`data/audit_log.db`) | Modified |
| `orchestration/graph.py` | `run_telecom_assistant()` now times the run and calls `record_call()`; the response includes `audit_id` | Modified |
| `ui/app.py` | UI split into three tabs; shows "Saved to audit log as `<id>`" after each reply | Modified |
| `.gitignore` | Ignores `data/audit_log.db` (it contains customer inquiries) | Modified |
| `README.md`, `HOW_IT_WORKS.md`, `TESTING.md`, `SETUP_NEW_MACHINE.md` | Documented the new features, tests and setup | Modified |
| `CHANGES.md` | This file | **New** |

## 1. Persistent audit log

**What it does.** Every call to `run_telecom_assistant()` is saved as one row in
`data/audit_log.db`, whether it succeeded or failed.

**What is stored per call**

| Column | Meaning |
|---|---|
| `audit_id` | Unique 12-character id |
| `created_at_utc` | UTC timestamp |
| `user_query` | The inquiry as typed |
| `status` | `SUCCESS` or `ERROR` |
| `workers_called`, `step_count` | Route taken, e.g. `BillingResolutionADK > CustomerCommsCrew` |
| `execution_trace` | Full, untruncated worker outputs (JSON) |
| `agent_context` | Accumulated findings passed to CrewAI |
| `final_response` | The reply written for the customer |
| `error_message` | Error text for failed calls |
| `duration_ms` | Total time for the call |
| `llm_provider`, `llm_model` | Which model answered (e.g. `claude-haiku-4-5-20251001`) |

**Design decisions**

- **Separate database file.** `init_db.py` drops and rebuilds `telecom_ops.db`;
  keeping the log in `audit_log.db` means resetting demo data never erases the
  history.
- **Logging can never break the assistant.** `record_call()` catches its own
  exceptions and returns `None`.
- **Failures are logged too**, with status `ERROR` and the message.
- **Not committed to git.** The file holds customer inquiries and replies.

## 2. Database Explorer and Audit Log tabs

The Streamlit app now has three tabs:

| Tab | Contents |
|---|---|
| **Assistant** | The original screen, unchanged apart from the audit id caption |
| **Audit Log** | Call count, successes, errors, average duration; filterable history; open any call to see its inquiry, reply, error and full trace; download the record as JSON |
| **Database Explorer** | See below |

**Database Explorer (read-only)**

- Switch between `telecom_ops.db` (business data) and `audit_log.db`.
- Overview of every table with its row count and a plain-English description.
- Inspect any table: columns, types, primary keys, foreign keys, and a row
  preview (adjustable).
- **"What's happening now"** one-click views: pending credit approvals, latest
  credits, open incidents, towers that are not OPERATIONAL, customers with a
  balance.
- A SQL box for your own queries. Only a single `SELECT` or `WITH` statement is
  accepted.

**Safety.** Databases are opened with SQLite's `mode=ro` flag, results are capped
at 500 rows, and anything else (for example `DROP TABLE billing_credits`) is
rejected with a message. This was tested: the table was untouched afterwards.

## 3. Tests

`tests/test_10_audit_log.py` adds 5 tests (35 to 40 in total), all offline:

1. A successful call is persisted with the correct route, step count, duration
   and decoded trace.
2. A failed call is stored with status `ERROR` and its message.
3. `list_calls()` returns newest first, and an empty list when no database exists.
4. `record_call()` returns `None` instead of raising when the file cannot be opened.
5. The audit database is a different file from the business database.

## 4. How this was verified

- Full test suite from a fresh clone of this repo: **40 passed**.
- Two live calls with both ADK services running (the CUST-10002 duplicate-charge
  case and the TX-512 diagnosis): both logged as `SUCCESS` with the correct
  routes, 2 steps each, using `claude-haiku-4-5`.
- The three UI tabs, the table switcher, the quick views, the safe SELECT and the
  blocked `DROP TABLE` were exercised with Streamlit's `AppTest` harness with no
  exceptions.

**Not done:** the UI was not viewed in a real browser window, and the audit
viewer's error-row display was covered by unit tests rather than a live failure.

## 5. Upgrading from `claude-rag`

No migration is needed. `data/audit_log.db` is created automatically on the first
call. There are no new dependencies (the explorer uses `pandas`, which Streamlit
already installs).
