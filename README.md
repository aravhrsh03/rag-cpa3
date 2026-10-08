# Prodapt AI Operations Center — Capstone Implementation (with Audit Log + Database Explorer)

Multi-framework agentic AI system for a fictional telecom provider, built per
`capstone-project-specification.html` (also kept under its original given
filename, `Agentic AI Project .html`): a **LangGraph** supervisor routes customer/staff
inquiries to specialist workers powered by **LlamaIndex** (document RAG +
semantic SQL), **Google ADK** (A2A microservices with SQL-backed tools), and
**CrewAI** (final customer-facing communications), surfaced through a
**Streamlit** UI with a full agent execution trace.

> Runs on **Anthropic Claude** by default (one `LLM_PROVIDER` switch in
> `.env` can point the whole stack at OpenAI instead) — see `HOW_TO_RUN.md`
> for the exact setup.

## Project layout

```
rag-cpa3/
├── capstone-project-specification.html  (spec, provided)
├── Agentic AI Project .html      (same spec, original given filename)
├── data/
│   ├── documents/*.txt           (6 policy files, provided)
│   ├── telecom_ops.db            (created by init_db.py)
│   ├── audit_log.db              (NEW: created on the first assistant call)
│   └── vector_index/             (created on first PolicyRAG query)
├── sql/01_schema.sql             (provided)
├── sql/02_seed_data.sql          (provided)
├── config.py                     (shared paths/env config)
├── init_db.py                    (builds telecom_ops.db from the SQL scripts)
├── common/db.py                  (shared SQLite helpers - no in-memory data)
├── common/audit.py               (NEW: persistent audit log of every assistant call)
├── llamaindex_rag/
│   ├── document_rag.py           (PolicyRAG: VectorStoreIndex over TXT docs)
│   └── sql_semantic_search.py    (NetworkAnalytics: ObjectIndex + SQL query engine)
├── adk-services/
│   ├── network_diagnostics/agent.py   (ADK A2A service, port 8001)
│   └── billing_resolution/agent.py    (ADK A2A service, port 8002)
├── orchestration/
│   ├── state.py                  (LangGraph AgentState)
│   ├── graph.py                  (supervisor + worker nodes + compiled graph)
│   ├── adk_remote_client.py      (RemoteA2aAgent wrapper for LangGraph)
│   └── crew_nodes.py             (CrewAI customer communications crew)
├── ui/app.py                     (Streamlit app: Assistant / Audit Log / Database Explorer tabs)
├── ui/db_explorer.py             (NEW: read-only database explorer + audit log viewer)
├── tests/                        (pytest suite, 40 tests; test_10 covers the audit log)
├── requirements.txt
└── .env.example
```

## New in this version

> A complete list of what changed, file by file, is in [`CHANGES.md`](CHANGES.md).

### 1. Persistent audit log
Every call to `run_telecom_assistant()` (success **or** failure) is saved as one
row in `data/audit_log.db` (`common/audit.py`):

| Column | Meaning |
|---|---|
| `audit_id`, `created_at_utc` | Unique id and UTC timestamp |
| `user_query` | The inquiry as typed |
| `status`, `error_message` | `SUCCESS` or `ERROR`, and the error text if any |
| `workers_called`, `step_count` | Route taken, e.g. `BillingResolutionADK > CustomerCommsCrew` |
| `execution_trace`, `agent_context` | Full, untruncated worker outputs |
| `final_response` | The reply sent to the customer |
| `duration_ms`, `llm_provider`, `llm_model` | Timing and which model answered |

Design choices: it lives in its **own file** so `python init_db.py` (which
rebuilds the business data) never erases history; logging **never raises**, so
an audit problem cannot break the assistant; and the file is git-ignored
because it contains customer inquiries.

### 2. Database Explorer and Audit Log tabs (Streamlit)
- **Audit Log tab:** call counts, success/error split, average duration, a
  filterable history, a per-call drill-down (full trace and reply) and a JSON
  download for any record.
- **Database Explorer tab:** read-only. Pick `telecom_ops.db` or
  `audit_log.db`; see every table with its row count and a plain-English
  description; inspect columns, foreign keys and a data preview; use one-click
  "what's happening now" views (pending credit approvals, latest credits, open
  incidents, towers that are not OPERATIONAL, customers with a balance); or run
  your own single `SELECT`/`WITH` query. Databases are opened with SQLite's
  `mode=ro` flag and anything other than a SELECT is rejected.

## Quick start on another machine

```bash
git clone https://github.com/aravhrsh03/rag-cpa3.git
cd rag-cpa3
python -m venv .venv            # Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env   -> then set ANTHROPIC_API_KEY
python init_db.py
# three terminals, venv active in each:
python adk-services/network_diagnostics/agent.py
python adk-services/billing_resolution/agent.py
streamlit run ui/app.py         # http://localhost:8501
```

Full details, including Windows pip tips and a sanity check, are in
`SETUP_NEW_MACHINE.md`.

## Setup

**Requires Python 3.10+.** A `.venv/` with every dependency already installed and
verified (see Verification below) is included in this folder — just activate it:

```bash
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

Setting up from scratch elsewhere:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Then, either way:

```bash
copy .env.example .env      # Windows (or: cp .env.example .env)
# edit .env and set ANTHROPIC_API_KEY
```

`LLM_PROVIDER` in `.env` is the one switch that drives every LLM call in the
project — the LangGraph supervisor, LlamaIndex's answer synthesis, CrewAI,
and (by default) the ADK agents too. It defaults to `anthropic`, so **only
`ANTHROPIC_API_KEY` is required** out of the box. Set `LLM_PROVIDER=openai`
and `OPENAI_API_KEY` to run the whole stack on OpenAI instead, or leave
`LLM_PROVIDER` as-is and set `ADK_MODEL=gemini-2.0-flash` + `GOOGLE_API_KEY`
to run just the ADK agents on Gemini.

## Run order

All commands are from the repository root (`rag-cpa3/`).

1. **Build the database** (creates `data/telecom_ops.db` from the provided SQL scripts):
   ```bash
   python init_db.py
   ```
   Expect `network_towers: 10 rows` and one flagged duplicate charge for `CUST-10002`.

2. **Start both ADK A2A services**, each in its own terminal:
   ```bash
   # Terminal 1
   python adk-services/network_diagnostics/agent.py
   # Terminal 2
   python adk-services/billing_resolution/agent.py
   ```
   Verify the agent cards are up:
   `http://localhost:8001/.well-known/agent-card.json`
   `http://localhost:8002/.well-known/agent-card.json`

3. **Start the Streamlit UI** in a third terminal:
   ```bash
   streamlit run ui/app.py
   ```
   The first PolicyRAG query will build and persist the vector index to
   `data/vector_index/` (subsequent runs load it instantly). The sidebar
   shows live status for the database, vector index, and both ADK services.

## Demo scenarios (from the spec, section 9)

| # | Try this query | Expected routing |
|---|---|---|
| 1 | "What is Prodapt's roaming policy for Western Europe?" | PolicyRAG → CustomerCommsCrew |
| 2 | "Which region had the most CRITICAL network outages?" | NetworkAnalytics → CustomerCommsCrew (answer: Midwest) |
| 3 | "My 5G keeps dropping in Austin near tower TX-512. Please diagnose." | NetworkDiagnosticsADK → CustomerCommsCrew |
| 4 | "Customer CUST-10002 was charged twice for Unlimited Plus. Investigate and apply credit." | BillingResolutionADK → CustomerCommsCrew (credit is PENDING_APPROVAL, $65.99 > $50 limit, balance stays $131.98) |
| 5 | "We had a 6-hour outage in the Midwest. Am I eligible for an SLA credit and what does policy say?" | NetworkAnalytics → PolicyRAG → CustomerCommsCrew |

More practice queries (with expected answers, useful while developing/demoing)
are in section 9.7 of `capstone-project-specification.html`.

## Verification

Everything below was actually run (not just written) against the real
libraries in `.venv`. The first group needed no LLM API calls at all:

- `init_db.py` builds the database; every scenario anchor from the spec
  (CUST-10002 balance/duplicate, TX-512/FL-090 latest-sample metrics, Midwest
  CRITICAL outage counts, packet-loss ranking) matches exactly.
- All three Billing Resolution tools (`lookup_billing_account`,
  `check_duplicate_charges`, `apply_billing_credit`) were called directly
  against the live database: the $50 auto-approval boundary (12.00 → APPLIED,
  50.00 → APPLIED, 65.99 → PENDING_APPROVAL) and the duplicate-detection query
  both match the spec's worked examples exactly. The DB was reset afterward.
- All three Network Diagnostics tools were called directly: TX-512 reproduces
  Scenario 3 exactly (OPERATIONAL, 3.8% packet loss, INC-8841 open); FL-090
  correctly reads OFFLINE/100% loss on the latest sample only.
- Both ADK services start for real, publish correct agent cards (with full
  tool schemas) at `/.well-known/agent-card.json` on ports 8001/8002, and
  `to_a2a` / `RemoteA2aAgent` construct without error against the installed
  `google-adk` version.
- The LlamaIndex document RAG index and the semantic-SQL `ObjectIndex` both
  build successfully (embedding model downloads and runs locally).
- The LangGraph graph compiles with all six expected nodes; the CrewAI crew
  constructs with both agents and both tasks.
- The Streamlit app was run through Streamlit's official `AppTest` harness:
  sidebar status detection, the Submit → response → Agent Execution Trace
  flow, the empty-trace message, and the `st.error` path were all exercised
  and render exactly as specified in section 6.8 — this caught and fixed one
  real bug (a bare ternary `st.success(...) if x else st.error(...)`
  statement that Streamlit's "magic" display feature can't parse; now plain
  `if/else`).

**All 5 required scenarios were additionally run live end-to-end** (real
Anthropic API calls, real supervisor routing, real LlamaIndex/ADK-agent/
CrewAI LLM calls) and matched the spec's expected values exactly:

- Scenario 1: PolicyRAG correctly retrieved Zone B roaming rates (Travel
  Pass $10/day, Business $5/day, Enterprise included) → CustomerCommsCrew.
- Scenario 2: NetworkAnalytics correctly identified Midwest with 6 CRITICAL
  outages → CustomerCommsCrew.
- Scenario 3: NetworkDiagnosticsADK reproduced TX-512 exactly (OPERATIONAL,
  -72 dBm, 3.8% packet loss, 85 Mbps, open incident INC-8841) →
  CustomerCommsCrew.
- Scenario 4: BillingResolutionADK found the duplicate $65.99 charge and
  correctly inserted a `PENDING_APPROVAL` credit, leaving the balance at
  $131.98 (verified in the database after the run) → CustomerCommsCrew,
  which correctly told the customer the credit was pending, not applied.
- Scenario 5: NetworkAnalytics found the 6-hour Midwest outage, PolicyRAG
  computed the exact SLA credit amounts from the policy formula ($22.50
  Business, $62.25 Enterprise pending, Consumer not eligible) →
  CustomerCommsCrew merged both into one coherent answer.

This run also surfaced and fixed one real dependency bug: see
`DEPENDENCIES_AND_NEXT_STEPS.md` §4 (`anthropic==0.125.0` pin) for the
`llama-index-llms-anthropic` / Anthropic SDK 1.x incompatibility that was
silently turning every PolicyRAG/NetworkAnalytics answer into an "Empty
Response" until fixed.

## Design notes / how this maps to the spec's build instructions (section 6)

- **No in-memory dictionaries**: every ADK tool (`adk-services/*/agent.py`)
  opens a fresh SQLite connection via `common/db.py` per call; nothing about
  towers, incidents, balances, or credits is cached in Python.
- **LlamaIndex used only for retrieval**: `document_rag.py` and
  `sql_semantic_search.py` expose plain functions via `as_query_engine()` /
  `SQLTableRetrieverQueryEngine` — no LlamaIndex agents/workflows.
- **Billing credit rule** (`apply_billing_credit` in
  `adk-services/billing_resolution/agent.py`): amount ≤ $50.00 → `APPLIED`,
  balance reduced; amount > $50.00 → `PENDING_APPROVAL`, balance unchanged —
  matches `billing_disputes_policy.txt` and the schema comments exactly.
- **Diagnostics use the latest sample only**: all tower_performance lookups
  filter to `MAX(recorded_at)` per tower, never an average.
- **Supervisor guarantees CustomerCommsCrew runs last**: `graph.py`'s
  `supervisor_node` uses an LLM with structured output for routing, but also
  hard-enforces (in code) that FINISH is never chosen until CustomerCommsCrew
  has already run, and caps total worker hops to prevent loops.
- **RemoteA2aAgent pattern**: `adk_remote_client.py` wraps each remote ADK
  service in a lightweight local proxy `Agent` (whose only sub_agent is the
  `RemoteA2aAgent`) and drives it with an ADK `Runner`; if a service's port
  isn't reachable, LangGraph gets back a clear message naming the exact
  command to start it, instead of an exception.

## Troubleshooting

- **"Database: Not found" in the sidebar** → run `python init_db.py` from the project root.
- **ADK service shows "Not running"** → start it in its own terminal (see step 2); check that nothing else is bound to port 8001/8002.
- **PolicyRAG/NetworkAnalytics errors mentioning API keys** → confirm the key matching your `LLM_PROVIDER` (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) is set in `.env` and the process was started after `.env` was saved.
- **Rebuilding the vector index** after editing a policy doc → delete `data/vector_index/` and resubmit a policy query.
- **Resetting demo data** (e.g. after applying credits during a walkthrough) → re-run `python init_db.py`; it drops and recreates every table.
