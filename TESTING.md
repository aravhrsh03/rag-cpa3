# Automated tests

`tests/` holds a pytest suite organized by build order, bottom of the stack
first: config, then the database, then each worker in isolation, then the
orchestration layer that wires them together. Each file is runnable on its
own, so you can verify one layer before trusting the next one built on top
of it.

None of these tests call a real LLM and none need an API key - they test
the deterministic logic (SQL rules, error handling, graph wiring, data
shapes) around the LLM calls, not the LLM calls themselves. The actual
LLM-routed behavior is covered separately by the manual walkthrough in
`HOW_TO_RUN.md`.

## Setup

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

`requirements-dev.txt` is just `requirements.txt` plus `pytest`. You do
**not** need to run `init_db.py` first - the tests that need a database
build their own throwaway copy (see `conftest.py` below).

## Running

```bash
# everything
pytest tests/ -v

# one stage at a time, in build order
pytest tests/test_01_config.py -v
pytest tests/test_02_database.py -v
pytest tests/test_03_network_diagnostics_tools.py -v
pytest tests/test_04_billing_resolution_tools.py -v
pytest tests/test_05_orchestration_state.py -v
pytest tests/test_06_adk_remote_client.py -v
pytest tests/test_07_orchestration_graph.py -v
pytest tests/test_08_rag_error_paths.py -v
pytest tests/test_09_crew_nodes_fallback.py -v
pytest tests/test_10_audit_log.py -v

# a single test by name
pytest tests/ -v -k test_apply_billing_credit_holds_over_limit_for_approval

# stop at the first failure instead of collecting every one
pytest tests/ -x
```

First run is slow (around 90-100 seconds) because stages 3, 4, 6, 7 and 9
import `google-adk`, `langchain`, and `crewai`, which are heavy packages.
Subsequent runs are faster once those modules are cached by Python.

## Shared fixtures (`tests/conftest.py`)

Three fixtures do the heavy lifting so individual test files stay short:

- **`seeded_db`** - builds a brand-new `telecom_ops.db` in a pytest temp
  directory by running the real `sql/01_schema.sql` then
  `sql/02_seed_data.sql` against it (the same two files `init_db.py` uses),
  then monkeypatches `common.db.DB_PATH` to point at that temp file for the
  duration of the test. Your real `data/telecom_ops.db` is never opened,
  read, or modified by the test suite.
- **`network_diagnostics_module`** / **`billing_resolution_module`** -
  load `adk-services/network_diagnostics/agent.py` and
  `adk-services/billing_resolution/agent.py` straight from their file path
  (the `adk-services` folder name has a hyphen, so it can't be imported as
  a normal `import adk_services...` package). Both call
  `pytest.importorskip("google.adk")` first, so if `google-adk` isn't
  installed yet, every test that needs them is skipped (not failed) with a
  clear reason instead of erroring.

Because these are plain pytest fixtures, any test that wants the seeded
database just adds `seeded_db` as a parameter - pytest handles setup/teardown
automatically (see any test in stages 2-4 for examples).

## Stage-by-stage

### Stage 1 - `test_01_config.py`
Target: `config.py`.
Checks: `DATA_DIR`/`DOCUMENTS_DIR`/`VECTOR_INDEX_DIR`/`SCHEMA_SQL_PATH`/
`SEED_SQL_PATH` all resolve under `PROJECT_ROOT`; `LLM_PROVIDER` is either
`"anthropic"` or `"openai"`; `BILLING_AUTO_APPROVAL_LIMIT` is `50.00`
(mirrors `billing_disputes_policy.txt`); `get_crewai_model_string()` returns
the right `"provider/model"` string for the active provider; `get_adk_model()`
wraps a `"provider/model"` string in `LiteLlm` but passes a bare model id
(e.g. a Gemini id) straight through.
Why first: every other module in the project imports from `config.py`, so
if this stage fails, nothing downstream can be trusted either.

### Stage 2 - `test_02_database.py`
Target: `common/db.py`.
Checks: `fetch_all`/`fetch_one` return the right rows and shapes against the
`seeded_db` fixture (all 10 towers, a known tower by id, `None` for a
missing row); `execute_write` inserts a row, commits it, and returns a
usable `lastrowid`; pointing `DB_PATH` at a file that doesn't exist raises
`DatabaseNotInitializedError` with the "run `python init_db.py`" message
instead of a raw `sqlite3` error.

### Stage 3 - `test_03_network_diagnostics_tools.py`
Target: the three async tool functions inside
`adk-services/network_diagnostics/agent.py` (`check_tower_status`,
`run_connectivity_diagnostics`, `get_regional_network_summary`), called
directly - not through the agent, the LLM, or the A2A service.
Checks: a known tower (`TX-512`) returns its latest performance sample and
no error; an unknown tower id returns `{"error": ...}`; `TX-512`'s
documented seed scenario (stays `OPERATIONAL` but packet loss climbs to
3.8% and 5G downlink falls to 85 Mbps across the week) produces a "Packet
loss" health flag and a recommendation that references the existing NOC
incident; `FL-090`'s documented seed scenario (OFFLINE with 100% packet
loss **only on the latest sample** - earlier samples that week looked fine)
is correctly flagged as an outage, proving the "latest sample, not a
weekly average" rule actually holds; a regional summary's status counts add
up to its tower count; an unknown region returns an error.
Skips if `google-adk` isn't installed.

### Stage 4 - `test_04_billing_resolution_tools.py`
Target: the three async tool functions inside
`adk-services/billing_resolution/agent.py` (`lookup_billing_account`,
`check_duplicate_charges`, `apply_billing_credit`).
Checks: `CUST-10002`'s balance matches the sum of their open charges; an
unknown customer id returns an error; the documented duplicate charge
`CHG-50022` is found by `check_duplicate_charges`; the $50 auto-approval
rule is exercised in both directions - a $40.00 credit is `APPLIED`
immediately and reduces `current_balance`, while a $65.99 credit (over the
limit) is stored as `PENDING_APPROVAL` and leaves `current_balance`
untouched; a non-positive credit amount is rejected with an error.
Skips if `google-adk` isn't installed.

### Stage 5 - `test_05_orchestration_state.py`
Target: `orchestration/state.py`.
Checks: `WORKERS` is exactly the five workers in spec order; `ROUTE_OPTIONS`
is `WORKERS + ["FINISH"]`; `MAX_WORKER_HOPS` is a positive int; `AgentState`
has exactly the seven fields the rest of the graph relies on. Pure data-shape
checks - no database, no LLM, no network, nothing to skip.

### Stage 6 - `test_06_adk_remote_client.py`
Target: `orchestration/adk_remote_client.py`.
Checks only the "the ADK service isn't running" path: `_service_reachable`
returns `False` for a closed local port; `diagnose_network_issue` and
`resolve_billing_issue`, pointed at a closed port via monkeypatch, each
return the actionable message telling you which `python adk-services/...`
command to run, instead of raising. The success path (talking to a real,
running ADK service) needs the services actually started on `:8001`/`:8002`
plus a configured LLM key - that's covered manually in `HOW_TO_RUN.md`, not
here.

### Stage 7 - `test_07_orchestration_graph.py`
Target: `orchestration/graph.py`.
Checks: `build_graph()` compiles without error; every worker name in
`WORKERS`, plus `"supervisor"`, shows up as a node in the compiled graph.
Deliberately does **not** call `run_telecom_assistant(...)` or invoke the
graph - that requires a real LLM call for the supervisor's routing
decision.

### Stage 8 - `test_08_rag_error_paths.py`
Target: `llamaindex_rag/document_rag.py` and
`llamaindex_rag/sql_semantic_search.py`.
Checks only the "not ready yet" branches: with `_configure_settings`
stubbed to a no-op (so no embedding model download and no LLM client
construction happens) and `DOCUMENTS_DIR`/`VECTOR_INDEX_DIR` (or `DB_PATH`)
pointed at empty temp paths, both modules return a clean
`"PolicyRAG is unavailable: ..."` / `"NetworkAnalytics is unavailable: ..."`
string instead of an unhandled exception. Runs fully offline - no
embedding model, no LLM, no real documents or database needed.

### Stage 9 - `test_09_crew_nodes_fallback.py`
Target: `orchestration/crew_nodes.py`.
Checks only the failure path: with `_build_crew` monkeypatched to raise,
`generate_customer_response` catches it and falls back to returning the
raw `agent_context` findings prefixed with `"CustomerCommsCrew failed..."`,
so a crew/LLM failure degrades gracefully instead of losing the upstream
workers' findings. The real two-agent crew (draft + review) needs a live
LLM call and is covered manually in `HOW_TO_RUN.md`.

### Stage 10 - `test_10_audit_log.py`
Target: `common/audit.py`.
Uses a temporary audit database. Checks that a successful call is persisted
with the right route, step count, duration and decoded trace; that a failed
call is stored with status `ERROR` and its message; that `list_calls` returns
newest first (and an empty list when no database exists yet); that
`record_call` returns `None` instead of raising when the audit file cannot be
opened; and that the audit database is a different file from the business
database, so `init_db.py` cannot wipe it. Fully offline.

## What this suite intentionally does not cover

- The supervisor's actual LLM-made routing decisions (`supervisor_node` in
  `orchestration/graph.py`).
- Real RAG answers from the policy documents, or real generated SQL from
  the semantic SQL engine - both need a built index/embedding model and a
  configured LLM key.
- The live two-agent CrewAI draft-then-review response.
- The ADK agents' actual tool-calling behavior via a real LLM, and the A2A
  services running end-to-end on `:8001`/`:8002`.
- The Streamlit UI (`ui/app.py`, `ui/db_explorer.py`). The three tabs and the read-only SQL guard were exercised separately with Streamlit's `AppTest` harness.

All of the above need a real `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` and are
exercised by hand using the five scenarios documented in `HOW_TO_RUN.md`.

## Troubleshooting

- **`ModuleNotFoundError: No module named 'google.adk'` (or `'crewai'`)
  during collection** - you're running against an environment where
  `requirements.txt` hasn't been fully installed. Stages 3, 4, 6, 7 and 9
  import those packages at module load time. Stages 3-4 are written to
  skip cleanly via `pytest.importorskip`; stages 6, 7, and 9 import
  `orchestration` modules that pull in `langchain`/`crewai` directly and
  will fail collection instead of skipping if those aren't installed - run
  `pip install -r requirements.txt` first.
- **`ImportError: cannot import name 'validate_core_schema' from
  'pydantic_core'`** - a `pydantic`/`pydantic_core` version mismatch in
  whichever Python environment actually ran (common if you accidentally
  ran the system Python instead of `.venv`'s). Confirm with
  `python -c "import sys; print(sys.executable)"` that you're using
  `.venv`'s interpreter, then reinstall: `pip install -r requirements.txt`.
- **Tests look like they hang for 1-2 minutes with no output** - that's
  normal on the first run; `google-adk`, `langchain`, and `crewai` are slow
  to import. Use `pytest tests/ -v` (not just `pytest tests/`) so passing
  tests print as they go instead of only at the end.

## Adding a new test

Follow the existing numbering and pattern:

1. Name the file `test_NN_<module-or-concern>.py`, where `NN` reflects
   where it sits in the build order relative to the existing files.
2. If it needs the database, add `seeded_db` as a parameter - don't touch
   `data/telecom_ops.db` directly.
3. If it needs a real dependency that might not be installed
   (`google-adk`, etc.), call `pytest.importorskip(...)` at the top rather
   than letting collection fail.
4. Prefer monkeypatching a module's already-imported names (e.g.
   `monkeypatch.setattr(document_rag, "DOCUMENTS_DIR", tmp_path)`) over
   reaching into `config` after other modules have already imported from
   it - `from config import X` binds `X` at import time, so patching
   `config.X` later has no effect on a module that already imported it.
