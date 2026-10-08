# Setting Up On A New Machine (After `git clone`)

**Read this first if you cloned this from GitHub.** A few things that exist
on the original build machine are deliberately **not** in this repo — a
2+ GB `.venv/`, your own `.env` secret, and generated/reproducible files —
so this is the exact, minimal path from a fresh clone to a running demo.

## What's in the repo vs. what you need to (re)build

| Path | In the repo? | Why |
|---|---|---|
| All source code (`*.py`), `sql/`, `data/documents/*.txt`, `requirements.txt`, docs | ✅ Yes | This is the actual project |
| `capstone-project-specification.html` + `Agentic AI Project .html` | ✅ Yes | The provided spec — kept under both the exact filename the spec's own directory tree expects, and its original given filename, for reference |
| `.venv/` | ❌ No (`.gitignore`) | ~2 GB of installed packages (torch, transformers, etc.) — never belongs in git; you rebuild it in one command below |
| `.env` | ❌ No (`.gitignore`) | Holds your personal `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) — never commit a real secret |
| `data/telecom_ops.db` | ❌ No (`.gitignore`) | Generated from `sql/*.sql` by `init_db.py` — a binary DB file doesn't belong in git when it's one command to regenerate |
| `data/vector_index/` | ❌ No (`.gitignore`) | Generated automatically the first time you ask a policy question — also just a rebuildable cache |
| `data/audit_log.db` | ❌ No (`.gitignore`) | The audit log of assistant calls. Created automatically on the first call; it holds customer inquiries, so it is never committed |

None of this is missing information — it's all either a one-command rebuild
or your own secret. Follow the steps below in order.

## Step-by-step

### 1. Prerequisites

- **Python 3.10 or newer** (this codebase was built and verified on 3.12).
  Check with `python --version`.
- **An Anthropic (Claude) API key** from
  https://console.anthropic.com/settings/keys — this project defaults to
  Claude. (An OpenAI key works too if you set `LLM_PROVIDER=openai` — see
  step 5.)
- Windows, macOS, or Linux all work — the commands below note where they
  differ.

### 2. Clone and enter the project

```bash
git clone https://github.com/aravhrsh03/rag-cpa3.git
cd rag-cpa3
```

### 3. Create and activate a virtual environment

```bash
python -m venv .venv
```

```powershell
# Windows (PowerShell or cmd)
.venv\Scripts\activate
```
```bash
# macOS / Linux
source .venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

This installs ~190 packages (LangGraph, LlamaIndex, Google ADK, CrewAI,
Streamlit, PyTorch for local embeddings, etc.) and can take several minutes,
mostly downloading `torch`. A few versions in `requirements.txt` are pinned
exactly (`crewai`, `crewai-tools`, `litellm`, `transformers`, `setuptools`)
specifically to avoid slow dependency-resolver backtracking and one real
`crewai`/`setuptools` incompatibility — see
`DEPENDENCIES_AND_NEXT_STEPS.md` §4 if you're curious why, but you don't
need to change anything.

> **Windows-specific note:** if `pip install` fails partway through with an
> error like `Could not install packages due to an OSError: ... The system
> cannot find the file specified: '...\Scripts\<something>.exe' ->
> '...deleteme'`, that's a real-time antivirus race condition on a newly
> written `.exe`, not a broken dependency list — it happened repeatedly
> against a global Python install while building this project. Simply
> **re-run `pip install -r requirements.txt`** (it resumes almost
> instantly for anything already installed); a couple of retries always
> got past it. Installing into a project-local `.venv` (which you're
> already doing here) also makes this far less likely than a global
> install.

### 5. Add your API key

```bash
cp .env.example .env        # macOS/Linux
copy .env.example .env      # Windows
```

Open `.env` and set:

```
ANTHROPIC_API_KEY=sk-ant-your-real-key-here
```

`LLM_PROVIDER=anthropic` is already the default in `.env.example`, so this
one key is all you need — it drives the LangGraph supervisor, LlamaIndex,
CrewAI, and (by default) the ADK agents too. To run the whole stack on
OpenAI instead, set `LLM_PROVIDER=openai` and `OPENAI_API_KEY=...`; to run
just the ADK agents on Gemini, see `DEPENDENCIES_AND_NEXT_STEPS.md` §5.

### 6. Build the database

```bash
python init_db.py
```

Expected output includes:

```
[OK] network_towers: 10 (expected 10)
[OK] CUST-10002 open duplicate charges: 1 (expected 1)
...
Database ready.
```

### 7. Sanity-check the install before running the full demo

```bash
python -c "import langgraph, llama_index.core, crewai, google.adk, streamlit; print('All core libraries import OK')"
```

If that prints cleanly, everything is installed correctly.

### 8. (Optional) Run the automated tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

All 40 tests should pass (about 2-3 minutes, mostly import time; no API calls are made).

### 9. Run it

Three terminals, from the project root, venv activated in each:

```bash
# Terminal 1
python adk-services/network_diagnostics/agent.py
# Terminal 2
python adk-services/billing_resolution/agent.py
# Terminal 3
streamlit run ui/app.py
```

Open http://localhost:8501. The UI has three tabs: **Assistant**, **Audit Log** and **Database Explorer**.

The first PolicyRAG question you ask will take a few extra seconds — that's
the local embedding model (`all-MiniLM-L6-v2`) downloading once and building
`data/vector_index/` for the first time. Every question after that is fast.

## Where to go next

- **`README.md` → "New in this version"** — the audit log and Database Explorer.
- **`HOW_TO_RUN.md`** — the full 15-minute demo script: exact queries to
  type for all 5 required scenarios, what result to expect from each, plus
  a longer table of practice queries.
- **`HOW_IT_WORKS.md`** — a complete architecture and code walkthrough of
  every file in the project.
- **`DEPENDENCIES_AND_NEXT_STEPS.md`** — what each dependency is for, why
  specific versions are pinned, what's verified vs. not, and known
  limitations.
- **`README.md`** — the short quick-reference version of all of the above.
