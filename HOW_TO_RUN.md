# How to Run the Full Demo — Prodapt AI Operations Center

This is a step-by-step script for starting the project from a cold machine
and running the complete demo: all 5 required scenarios, what to type, what
to watch for in the UI, and how to reset between runs. It assumes you're in
`D:\ragproject2\capstone-project\` (or wherever you copied this folder).

A working `.venv/` with every dependency already installed is included, so
you do **not** need to run `pip install` unless you deleted it or moved the
project to a machine that doesn't have it.

---

## 1. One-time setup (do this once)

### 1.1 Get an API key ready

By default this project runs entirely on **Anthropic (Claude)**. Get a key
(starts with `sk-ant-...`) from https://console.anthropic.com/settings/keys.
This project's LLM calls — the LangGraph supervisor's routing decisions,
LlamaIndex's answer synthesis, the CrewAI writer/reviewer, and (by default)
the ADK agents' tool-calling — all go through this one key.

(If you'd rather run on OpenAI instead, see the `LLM_PROVIDER` note in step
1.2 — everything below still applies, just with an OpenAI key.)

### 1.2 Create your `.env` file

From the project root:

```powershell
copy .env.example .env
```

Open `.env` in any text editor and fill in:

```
ANTHROPIC_API_KEY=sk-ant-your-real-key-here
```

Everything else in `.env.example` has a working default — leave it as-is.
`LLM_PROVIDER=anthropic` is already the default, so this one key is all you
need. To run on OpenAI instead, set `LLM_PROVIDER=openai` and
`OPENAI_API_KEY=...`; to switch just the ADK agents to Gemini, see
`DEPENDENCIES_AND_NEXT_STEPS.md`.

**Never commit `.env` to git or share it** — it holds your real key.
`.gitignore` already excludes it.

### 1.3 Confirm the database and vector index are already built

They ship pre-built in this folder (`data/telecom_ops.db`,
`data/vector_index/`), so you can skip straight to Step 2. If you ever want
to reset the demo data to a clean state (e.g. after applying test credits),
re-run:

```powershell
.venv\Scripts\activate
python init_db.py
```

This drops and rebuilds every table from `sql/01_schema.sql` +
`sql/02_seed_data.sql`, and prints a verification summary. You should see:

```
[OK] network_towers: 10 (expected 10)
[OK] CUST-10002 open duplicate charges: 1 (expected 1)
```

---

## 2. Start the three processes

The system is three independent processes talking over HTTP. Open **three
separate terminals**, all starting from the project root
(`D:\ragproject2\capstone-project\`), and activate the venv in each one.

### Terminal 1 — Network Diagnostics ADK service (port 8001)

```powershell
.venv\Scripts\activate
python adk-services\network_diagnostics\agent.py
```

Expected output:

```
Starting Network Diagnostics ADK service on port 8001 ...
Agent card: http://localhost:8001/.well-known/agent-card.json
INFO:     Uvicorn running on http://0.0.0.0:8001 (Press CTRL+C to quit)
```

(You'll also see a few `UserWarning: [EXPERIMENTAL]` lines from Google ADK's
A2A support — that's expected, it's Google's own warning about the A2A
feature's maturity, not an error.)

### Terminal 2 — Billing Resolution ADK service (port 8002)

```powershell
.venv\Scripts\activate
python adk-services\billing_resolution\agent.py
```

Same kind of output, on port 8002.

**Sanity check both services** by opening these two URLs in a browser (or
`curl`) — each should return a JSON "agent card" describing the agent and
its tools:

- http://localhost:8001/.well-known/agent-card.json
- http://localhost:8002/.well-known/agent-card.json

### Terminal 3 — Streamlit UI

```powershell
.venv\Scripts\activate
streamlit run ui\app.py
```

This opens your browser to `http://localhost:8501`. If it doesn't open
automatically, click the "Local URL" it prints.

---

## 3. Verify the sidebar before you start

Look at the left sidebar of the Streamlit app. Before running any query,
confirm all four status lines are green:

- ✅ **Database: Ready** (`data/telecom_ops.db`)
- ✅ **Vector index: Built** (`data/vector_index/`)
- ✅ **Network Diagnostics ADK (8001): Running**
- ✅ **Billing Resolution ADK (8002): Running**

If either ADK line is red ("Not running"), the sidebar itself prints the
exact command to start it. If the database line is red, run `python
init_db.py`. If the vector index line just says "not built yet" (blue info
box, not an error), that's fine — it builds automatically the first time you
ask a policy question, which takes a few extra seconds only on that first
query.

Below the status lines, the **Framework map** table shows which framework
answers which kind of question — useful to have open during a live demo so
you can point at it when explaining routing.

---

## 4. The 15-minute demo script

This mirrors the evaluation demo script in the spec (section 10.1). Talk
through the business problem first if you're presenting to an audience, then
run these five queries in order, pointing at the **Agent Execution Trace**
expander after each one (it's expanded by default) to show exactly which
worker(s) ran.

### Scenario 1 — Policy / FAQ (LlamaIndex Document RAG)

**Type into the inquiry box:**
```
What is Prodapt's roaming policy for Western Europe?
```

**Expected trace:** `Step 1 — PolicyRAG` → `Step 2 — CustomerCommsCrew`

**What to point out:** PolicyRAG's step output cites Zone B facts straight
from `roaming_policy.txt` (Travel Pass $10.00/day with 5GB, Business
Unlimited pays $5.00, Enterprise Mobile includes Zone B) — no SQL and no ADK
service were touched for this question.

### Scenario 2 — Network Analytics (LlamaIndex Semantic SQL)

**Type:**
```
Which region had the most CRITICAL network outages?
```

**Expected trace:** `Step 1 — NetworkAnalytics` → `Step 2 — CustomerCommsCrew`

**What to point out:** The answer should name **Midwest** — the seed data
has 6 CRITICAL Midwest outages all-time vs. 2 Northeast and 1 Southeast.
Mention that `sql_semantic_search.py` never hard-codes this — it semantically
picks the `network_outages` table from an embedded description, then an LLM
writes and runs the actual `SELECT ... GROUP BY region` against SQLite.

### Scenario 3 — Network Diagnostics (ADK A2A + SQL tools)

**Type:**
```
My 5G keeps dropping in Austin near tower TX-512. Please diagnose.
```

**Expected trace:** `Step 1 — NetworkDiagnosticsADK` → `Step 2 — CustomerCommsCrew`

**What to point out:** The step output should mention tower **TX-512**,
status **OPERATIONAL**, latest packet loss **3.8%**, downlink **85 Mbps**
(degraded for a 5G site), and open incident **INC-8841**. This is the
strongest moment to prove "not hard-coded data" — you can open
`data/telecom_ops.db` in a SQLite browser (or run the query in
`HOW_IT_WORKS.md`'s SQL appendix) and show the exact same numbers sitting in
the `tower_performance` table.

### Scenario 4 — Billing Dispute (ADK A2A + SQL tools)

**Type:**
```
Customer CUST-10002 was charged twice for Unlimited Plus. Investigate and apply credit.
```

**Expected trace:** `Step 1 — BillingResolutionADK` → `Step 2 — CustomerCommsCrew`

**What to point out — this is the money moment of the demo:**
- The step output should say a duplicate **$65.99** Unlimited Plus charge
  (`CHG-50022`) was found.
- Because $65.99 is **over the $50.00 auto-approval limit**, the credit is
  inserted with status **PENDING_APPROVAL**, and the customer's balance
  **stays at $131.98** (it does *not* drop).
- The final CrewAI response should tell the customer the credit is
  *submitted for approval*, not that it's already been applied — this is
  the Quality Reviewer agent enforcing accuracy against the specialist's
  findings.
- If you want to show the $50-or-under path instead, resubmit with a
  different customer (see the billing table in §5 below) — e.g. CUST-10027
  gets an immediate **APPLIED** credit.

> **Heads-up:** this scenario actually writes a row into `billing_credits`
> and can change `billing_accounts.current_balance`. Run `python
> init_db.py` after your demo (or before a second run) to reset it back to
> the pristine seed state.

### Scenario 5 — Combined Multi-Worker Flow

**Type:**
```
We had a 6-hour outage in the Midwest. Am I eligible for an SLA credit and what does policy say?
```

**Expected trace:** `Step 1 — NetworkAnalytics` → `Step 2 — PolicyRAG` →
`Step 3 — CustomerCommsCrew`

**What to point out:** This is the one query that needs *two* specialists
before the final answer — the supervisor first asks NetworkAnalytics for the
outage facts (Midwest's `OUT-2026-0912`: CRITICAL, 6 hours, 8,500 customers),
then routes to PolicyRAG for the SLA eligibility rule (Business ≥4h, Consumer
≥8h, Enterprise ≥2h — so a 6-hour outage qualifies Business and Enterprise
accounts but not Consumer). CrewAI then merges both into one coherent
eligibility answer. This is the clearest proof the LangGraph supervisor can
chain more than one worker before finishing.

---

## 5. Extra practice queries (not required for grading, useful for a longer demo)

Straight from spec section 9.7 — use these if you want to show more range,
or to rehearse before the graded run. Every value below was directly
verified against the live database while building this project.

**Billing — testing every side of the $50 limit** (route:
BillingResolutionADK → CustomerCommsCrew):

| Query | Correct outcome |
|---|---|
| `Chris Dalton (CUST-10027) was charged twice for International Day Pass. Investigate.` | APPLIED, balance reduced by $12.00 |
| `Maya Chen (CUST-10008) was charged twice for Japan pay-per-use data. Investigate.` | APPLIED, balance reduced by $36.00 |
| `Ben Carter (CUST-10128) was charged twice for a Travel Pass Zone B bundle. Investigate.` | APPLIED — exactly $50.00 does not exceed the limit |
| `Derek Holt (CUST-10011) was charged twice for a device installment. Investigate.` | PENDING_APPROVAL, balance unchanged ($80 > $50) |

**Billing — cases where no credit should be issued** (good for showing the
system doesn't over-credit):

| Query | Correct outcome |
|---|---|
| `CUST-10136 was charged 60 dollars for a Japan Travel Pass. Is that a duplicate?` | No — 5 Zone C days at $12.00 each, matches published rate |
| `CUST-10172 disputes 18.40 of Brazil data.` | No — single Zone D line at the published rate, not a duplicate |
| `CUST-10071 was double-charged for voicemail.` | Already resolved in August (an APPLIED credit exists); September bill has no open duplicate |

**Network — "latest sample, not the week average"**:

| Query | Worker | Correct outcome |
|---|---|---|
| `Which towers have the highest packet loss right now?` | NetworkAnalytics | FL-090 at 100% (offline), then TX-208 at 8.6%, then IL-221 at 5.4% |
| `What is wrong with tower FL-090 in Miami?` | NetworkDiagnosticsADK | OFFLINE on the latest sample, 100% packet loss, open incident INC-8702 |
| `Summarize the Southwest region.` | NetworkDiagnosticsADK | TX-512 OPERATIONAL, TX-208 DEGRADED |
| `How long was the Midwest outage on 12 September 2026, and how many customers?` | NetworkAnalytics | OUT-2026-0912: CRITICAL, 6 hours, 8,500 customers, RESOLVED |

**Policy — straight from the documents:**

| Query | Correct outcome |
|---|---|
| `What does roaming cost in Japan? I am on Unlimited Plus.` | Zone C: Travel Pass $12/day (2GB then 256kbps), or pay-per-use $0.20/MB, $100 spend cap; Unlimited Plus does not include Zone C |
| `Can I trade in an iPhone 13?` | $180 in good condition (see `device_upgrade_policy.txt` for exact tiers) |
| `Why is my 5G slow indoors?` | Buildings cut mid-band signal ~10–20 dB and block mmWave; Wi-Fi calling included |

---

## 6. Shutting down / resetting between demo runs

- Stop each terminal with `Ctrl+C`.
- To reset the database to the pristine seed state (undo any credits applied
  during a demo): `python init_db.py`.
- The vector index (`data/vector_index/`) never needs to be rebuilt unless
  you edit a file in `data/documents/` — delete the folder and resubmit a
  policy question to force a rebuild.

## 7. If something goes wrong mid-demo

See the **Troubleshooting** section of `README.md` and the **Known
limitations** section of `DEPENDENCIES_AND_NEXT_STEPS.md`. The short version:
- A red status in the sidebar tells you exactly what to run to fix it.
- If the graph throws, the UI shows a plain `st.error` with the message —
  it never leaves you looking at a blank or broken screen.
- If an ADK service was killed mid-run, LangGraph's error message names the
  exact command to restart it.
