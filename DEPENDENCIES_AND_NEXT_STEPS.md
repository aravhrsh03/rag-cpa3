# Dependencies, Environment Notes & What's Left For You To Do

This file covers three things: exactly what's installed and why, what's
already done for you vs. what you still need to do before this runs live,
and what was and wasn't possible to verify without spending your API
credits.

---

## 1. What's already done for you

- **A working `.venv/`** with all ~190 packages installed and individually
  verified against the real libraries (see `README.md`'s Verification
  section) — you do not need to run `pip install` on this machine.
- **The database** (`data/telecom_ops.db`), built from the provided
  `sql/01_schema.sql` + `sql/02_seed_data.sql` and verified row-by-row
  against every scenario anchor in the spec.
- **The vector index** (`data/vector_index/`), pre-built from the six policy
  documents, so the first PolicyRAG query won't pay the embedding cost.

## 2. What you still need to do

This is the complete list — nothing else is required:

1. **Provide a real `ANTHROPIC_API_KEY`.** Copy `.env.example` to `.env` and
   fill it in. Every LLM call in this project — the LangGraph supervisor,
   LlamaIndex's answer synthesis, CrewAI, and (by default) the ADK agents'
   own tool-calling — goes through this one key by default (`LLM_PROVIDER=
   anthropic`). Without it, every worker that needs an LLM will return a
   clear error string rather than crash, but nothing will actually answer.
2. **Start the three processes** (two ADK services + Streamlit) in three
   terminals — see `HOW_TO_RUN.md` for exact commands.
3. **(Optional)** To run the whole stack on OpenAI instead of Anthropic, set
   `LLM_PROVIDER=openai` and `OPENAI_API_KEY=...` in `.env`. To run just the
   ADK agents on Gemini regardless of `LLM_PROVIDER`, set
   `ADK_MODEL=gemini-2.0-flash` and `GOOGLE_API_KEY=...` (see §5 below for
   exactly how this switch works).

That's it. Everything else — the database, the index, the environment — is
already built and checked.

## 3. Full dependency list and what each one is for

From `requirements.txt`, grouped by role:

| Package(s) | Role |
|---|---|
| `python-dotenv` | Loads `.env` into environment variables (`config.py`) |
| `setuptools<81` | See §4 — pinned so `crewai`'s `pkg_resources` import keeps working |
| `langgraph`, `langchain-core` | The supervisor graph and message types |
| `langchain-anthropic`, `langchain-openai` | The supervisor's structured-output routing LLM — `config.get_chat_llm()` picks one based on `LLM_PROVIDER` |
| `llama-index-core` | `VectorStoreIndex`, `SQLDatabase`, `ObjectIndex`, query engines |
| `llama-index-llms-anthropic`, `llama-index-llms-openai` | LlamaIndex's LLM wrappers for answer synthesis + SQL generation — `config.get_llamaindex_llm()` picks one based on `LLM_PROVIDER` |
| `llama-index-embeddings-huggingface`, `sentence-transformers`, `transformers` | The local embedding model (`all-MiniLM-L6-v2`) — no API key needed for embeddings, used regardless of `LLM_PROVIDER` |
| `sqlalchemy` | LlamaIndex's `SQLDatabase` wrapper needs a SQLAlchemy engine over `telecom_ops.db` |
| `google-adk[a2a]` | The ADK `Agent`, `to_a2a`, `RemoteA2aAgent`, `Runner`, session service — both ADK microservices and the LangGraph-side client |
| `litellm` | Lets ADK agents call Anthropic or OpenAI models (via `LiteLlm(model="anthropic/..."` or `"openai/..."`) instead of requiring Gemini/`GOOGLE_API_KEY` |
| `crewai`, `crewai-tools` | The two-agent customer communications crew — its LLM string also follows `LLM_PROVIDER` via `config.get_crewai_model_string()` |
| `streamlit` | The UI |
| `httpx` | Health-checking the ADK services' agent-card URLs (used by both the UI sidebar and `adk_remote_client.py`) |

## 4. Why some versions are pinned exactly (not just `>=`)

While installing this stack, `pip`'s resolver and Windows itself threw up
some real obstacles. Documenting them here so you understand why the pins
exist and don't "helpfully" loosen them:

- **`crewai==0.86.0` and `crewai-tools==0.76.0`** — `crewai` depends on
  `crewai-tools` with an *open-ended* version range. Because `crewai-tools`
  pulls in a large, mostly-unrelated toolkit (chromadb, lancedb, docker,
  kubernetes client, pytube, stagehand — none of which this project actually
  uses; we only import `Agent`, `Task`, `Crew`, `Process` from bare
  `crewai`), letting `pip` freely pick the newest compatible version caused
  it to backtrack through dozens of releases for several minutes on every
  install. Pinned to the exact version `pip`'s resolver converges to anyway.
- **`litellm==1.93.1`** — an open range let `pip` pick a version whose only
  distribution was a source tarball (no prebuilt Windows wheel), which then
  tried to build via Poetry's backend and hung for minutes. Pinned to a
  version with a working `cp312-win_amd64` wheel.
- **`transformers<4.49`** — without this ceiling, `pip` spent a long time
  backtracking through `transformers` releases to satisfy both
  `sentence-transformers` and `crewai`'s indirect constraints at once.
- **`setuptools<81`** — `crewai==0.86.0`'s own telemetry module
  (`crewai/telemetry/telemetry.py`) still does `import pkg_resources`, which
  ships inside `setuptools`. Very recent `setuptools` releases dropped
  `pkg_resources` entirely, which broke `import crewai` outright
  (`ModuleNotFoundError: No module named 'pkg_resources'`) until this was
  pinned back.
- **`anthropic==0.125.0`** — found by live-testing PolicyRAG with a real
  Anthropic key: `llama-index-llms-anthropic` (0.12.2, the latest release as
  of writing) still calls `Messages.create(temperature=...)` in the pre-1.0
  Anthropic SDK's call shape. Anthropic's SDK crossed into a breaking 1.x
  major version, and with an unpinned `anthropic` dependency, `pip` installs
  1.9.0 by default, which raises `TypeError: Messages.create() got an
  unexpected keyword argument 'temperature'` on every LlamaIndex query —
  silently swallowed by LlamaIndex's response synthesizer into an "Empty
  Response" rather than a visible crash. `langchain-anthropic` (used by the
  supervisor) already supports 1.x fine, so this is specifically a
  `llama-index-llms-anthropic` compatibility gap; pinning `anthropic` to its
  latest 0.x release fixes both integrations at once (it satisfies
  `langchain-anthropic`'s own `anthropic<2.0.0,>=0.120.0` constraint too).
  If a future `llama-index-llms-anthropic` release supports the 1.x SDK,
  this pin can be lifted.

None of these pins reflect a real incompatibility with newer versions of
*this project's own code* — they exist purely to keep `pip install` fast and
successful given how `crewai`'s dependency tree is currently shaped. If a
future `crewai` release depends on `crewai-tools` more narrowly, or drops
the `pkg_resources` import, these pins can likely be relaxed.

## 5. The provider switch (`LLM_PROVIDER` and `config.py`'s helper functions)

This project can run its entire LLM stack on **Anthropic** (the default) or
**OpenAI**, controlled by exactly one setting: `LLM_PROVIDER` in `.env`.
Four functions in `config.py` read it and return the right client for each
framework:

| Function | Used by | `LLM_PROVIDER=anthropic` (default) | `LLM_PROVIDER=openai` |
|---|---|---|---|
| `get_chat_llm()` | LangGraph supervisor (`orchestration/graph.py`) | `ChatAnthropic(model=ANTHROPIC_MODEL)` | `ChatOpenAI(model=OPENAI_MODEL)` |
| `get_llamaindex_llm()` | Both LlamaIndex modules (`llamaindex_rag/`) | `llama_index.llms.anthropic.Anthropic` | `llama_index.llms.openai.OpenAI` |
| `get_crewai_model_string()` | CrewAI (`orchestration/crew_nodes.py`) | `"anthropic/{ANTHROPIC_MODEL}"` | `"openai/{OPENAI_MODEL}"` |
| `get_adk_model()` | Both ADK services + `adk_remote_client.py` | `LiteLlm("anthropic/{ANTHROPIC_MODEL}")` | `LiteLlm("openai/{OPENAI_MODEL}")` |

`get_adk_model()` reads `ADK_MODEL` specifically (not `LLM_PROVIDER`
directly), but `ADK_MODEL`'s own default is computed *from* `LLM_PROVIDER`
(`config._DEFAULT_ADK_MODEL`) — so leaving `ADK_MODEL` unset in `.env` means
the ADK agents automatically follow whatever `LLM_PROVIDER` says. Any
`provider/model`-shaped string (`"openai/..."`, `"anthropic/..."`) gets
wrapped with `google.adk.models.lite_llm.LiteLlm` so ADK calls that provider
instead of its native Gemini client; a bare model id like
`gemini-2.0-flash` (no `/`) is passed straight through to Gemini instead,
which needs `GOOGLE_API_KEY`. This means you can mix providers — e.g. run
the supervisor/RAG/CrewAI on Claude while explicitly pinning the ADK agents
to Gemini — by setting `ADK_MODEL` explicitly alongside `LLM_PROVIDER`.

**Model choice**: `ANTHROPIC_MODEL` defaults to `claude-haiku-4-5-20251001`
and `OPENAI_MODEL` to `gpt-4o-mini` — both fast, inexpensive models, chosen
for the same reason: this project makes many small LLM calls per query
(routing, tool-calling, synthesis, draft, review), so a cheap/fast model
keeps the demo responsive and inexpensive. Set either env var to a larger
model (e.g. `claude-sonnet-5`) if you want higher-quality answers at a
higher per-call cost.

## 6. What was verified, and what genuinely needs your API key

Everything below was **actually executed** against the real installed
libraries while building this project (not just read/reviewed):

**Verified without needing an LLM call** (pure logic / local model / server
startup):
- Database build and every business-rule query (balance invariants,
  duplicate detection, packet-loss ranking, CRITICAL outage counts) —
  matched the spec's worked examples exactly.
- All 6 ADK tool functions, called directly against the live database.
- Both ADK services actually starting and publishing correct agent cards
  with full tool schemas at `/.well-known/agent-card.json`.
- The LlamaIndex document index and the semantic-SQL `ObjectIndex` both
  building successfully (this exercises the local embedding model, no API
  key needed).
- The LangGraph graph compiling with all 6 expected nodes.
- The CrewAI crew constructing with both agents and tasks.
- The full Streamlit UI, via the official `AppTest` harness: sidebar status
  detection, the Submit → response → trace flow (with a mocked graph
  result), the empty-trace message, and the error path.

**Not run, because it spends your real API credits**: an actual live
query going all the way through — supervisor LLM routing decision →
LlamaIndex/ADK-agent LLM calls → CrewAI's draft + review LLM calls → final
answer. Every individual link in that chain has been verified above; the
only thing not exercised is the live LLM reasoning itself, which requires
your key and this project's own README explicitly avoids spending your
money without asking first. Once you add your key and run the demo script
in `HOW_TO_RUN.md`, you'll be exercising exactly this path for the first
time.

## 7. Known limitations / things intentionally not built

These are all either explicitly marked optional in the spec, or out of
scope for what was asked:

- **No sidebar sample-query buttons or query history** — the spec (§6.8.1)
  explicitly says *not* to add sample-query shortcuts to the sidebar for
  this deliverable, and query history is listed as an optional enhancement
  (§6.8.6) that "not required for full marks."
- **`billing_disputes` table is read-only in code** — the spec's three
  required Billing Resolution tools (`lookup_billing_account`,
  `check_duplicate_charges`, `apply_billing_credit`) never mention writing
  to `billing_disputes`, so this project doesn't create/update dispute rows
  when a credit is applied. If your presentation wants to show a dispute
  being opened/resolved automatically, that would be a genuine extension,
  not part of the graded scope per the spec's own tool list.
- **No human-approval workflow for `PENDING_APPROVAL` credits** — the spec
  says "Humans remain in the loop for approvals (e.g., credits over $50 per
  policy)" (§1.5) as a business-value statement, not a UI requirement; this
  project correctly *creates* the `PENDING_APPROVAL` row and *reports* it
  accurately, but there's no supervisor-approval screen (not asked for).
- **Single-turn conversations** — each Streamlit submission is one
  independent run of the graph; there's no multi-turn chat memory across
  submissions. The spec's scenarios are all single-inquiry demos, so this
  matches what's actually required.

## 8. Ideas if you want to extend this further

Not required, but natural next steps if you want to go beyond the spec:

- Add a real approval UI for `PENDING_APPROVAL` credits (a second Streamlit
  page or an admin toggle that flips a credit's status to `APPLIED` and
  reduces the balance).
- Add `billing_disputes` row creation/update alongside `apply_billing_credit`
  for a full audit trail of the dispute lifecycle, not just the credit.
- Add persistent chat/session memory so a follow-up question ("what about my
  other charge?") can reference the previous turn's `agent_context`.
- Containerize the two ADK services (each is already an independent process
  — the spec's own rationale for A2A is "network and billing teams can
  deploy/update agents independently," which Docker would make literal).
- Add a fourth or fifth policy document and confirm PolicyRAG picks it up
  after deleting `data/vector_index/` and letting it rebuild.

## 9. Cost awareness

Once you add your key, every submitted inquiry makes multiple LLM API calls
against your configured provider: the supervisor's routing decision (once
per worker hop), the LlamaIndex query engine(s) invoked, the ADK agent's own
tool-calling loop (1–3 calls per tool used), and the CrewAI draft + review (2
calls). A typical single-worker query (Scenario 1–4) is roughly 4–8 small
model calls; the combined Scenario 5 roughly doubles that. This is
inexpensive at Claude Haiku or `gpt-4o-mini` prices, but worth knowing if
you're running the full practice query list in §5 of `HOW_TO_RUN.md` many
times while rehearsing.

## 10. If your environment doesn't have this `.venv` (fresh machine)

If you copy just the source files to a machine without this `.venv/`
(different OS, or you deleted it to save space), rebuild it with:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

**Requires Python 3.10+** (this project uses `X | None` union type hints and
`dict[str, Any]`-style built-in generics throughout, which need 3.10+).
Tested and built against Python 3.12.

On Windows specifically, if `pip install` fails partway through with an
error like `Could not install packages due to an OSError: ... The system
cannot find the file specified: '...\Scripts\<something>.exe' ->
'...deleteme'` — this is a real-time antivirus race condition on newly
written console-script `.exe` files, not a problem with this project's
dependency list. It happened repeatedly while building this project against
the *global* Python installation, on a different `.exe` each time, and was
fully resolved by installing into a **project-local virtual environment**
instead (exactly what `.venv/` here is) rather than the system Python. If
you ever need to rebuild from scratch and hit this, creating a fresh
`.venv` and installing into that (rather than retrying against a global
Python) is the fix that actually worked here.
