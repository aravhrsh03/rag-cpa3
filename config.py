"""
Prodapt AI Operations Center - shared configuration.

Every module in this project (LlamaIndex RAG, ADK services, LangGraph
orchestration, CrewAI, Streamlit UI) imports paths and settings from here
instead of hard-coding them, so the project can be pointed at a different
.env or data folder in one place.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
DATA_DIR = PROJECT_ROOT / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
VECTOR_INDEX_DIR = DATA_DIR / "vector_index"
DB_PATH = DATA_DIR / "telecom_ops.db"
# Audit log lives in its own file so `init_db.py` (which rebuilds telecom_ops.db)
# never wipes the history of past calls.
AUDIT_DB_PATH = DATA_DIR / "audit_log.db"

SQL_DIR = PROJECT_ROOT / "sql"
SCHEMA_SQL_PATH = SQL_DIR / "01_schema.sql"
SEED_SQL_PATH = SQL_DIR / "02_seed_data.sql"

# --------------------------------------------------------------------------
# LLM / embedding configuration (LlamaIndex + CrewAI + LangGraph supervisor)
# --------------------------------------------------------------------------
# LLM_PROVIDER is the one switch that drives every LLM call in the project
# (supervisor routing, LlamaIndex answer synthesis, CrewAI, and - unless
# overridden - the ADK agents too): "anthropic" or "openai".
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# --------------------------------------------------------------------------
# Google ADK configuration
# --------------------------------------------------------------------------
# If ADK_MODEL isn't set explicitly, it defaults to match LLM_PROVIDER, so
# one env var switches the whole stack. Set ADK_MODEL=gemini-2.0-flash (plus
# GOOGLE_API_KEY) to use Gemini for just the ADK agents regardless of
# LLM_PROVIDER.
_DEFAULT_ADK_MODEL = (
    f"anthropic/{ANTHROPIC_MODEL}" if LLM_PROVIDER == "anthropic" else f"openai/{OPENAI_MODEL}"
)
# `or` (not a plain os.getenv default) so an empty ADK_MODEL= line in .env
# still falls through to the LLM_PROVIDER-matched default, not "".
ADK_MODEL = os.getenv("ADK_MODEL") or _DEFAULT_ADK_MODEL
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

NETWORK_DIAGNOSTICS_PORT = int(os.getenv("NETWORK_DIAGNOSTICS_PORT", "8001"))
BILLING_RESOLUTION_PORT = int(os.getenv("BILLING_RESOLUTION_PORT", "8002"))

NETWORK_DIAGNOSTICS_AGENT_URL = os.getenv(
    "NETWORK_DIAGNOSTICS_AGENT_URL", f"http://localhost:{NETWORK_DIAGNOSTICS_PORT}"
)
BILLING_RESOLUTION_AGENT_URL = os.getenv(
    "BILLING_RESOLUTION_AGENT_URL", f"http://localhost:{BILLING_RESOLUTION_PORT}"
)

AGENT_CARD_PATH = "/.well-known/agent-card.json"

# --------------------------------------------------------------------------
# Business rules (mirrored from billing_disputes_policy.txt / 01_schema.sql)
# --------------------------------------------------------------------------
BILLING_AUTO_APPROVAL_LIMIT = 50.00


def get_adk_model():
    """
    Resolve the ADK_MODEL setting into whatever google.adk.agents.Agent(model=...)
    expects.

    - "provider/model" strings (e.g. "openai/gpt-4o-mini", "anthropic/claude-...")
      are wrapped with LiteLlm so ADK calls that provider instead of Gemini.
    - A bare model id (e.g. "gemini-2.0-flash") is passed straight through to
      ADK's native Gemini client, which requires GOOGLE_API_KEY.
    """
    model_name = ADK_MODEL
    if "/" in model_name:
        from google.adk.models.lite_llm import LiteLlm

        return LiteLlm(model=model_name)
    return model_name


def get_chat_llm(temperature: float = 0.0):
    """
    LangChain chat model for the LangGraph supervisor's structured-output
    routing decision (ChatOpenAI/ChatAnthropic both support
    .with_structured_output(...)).
    """
    if LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=ANTHROPIC_MODEL, api_key=ANTHROPIC_API_KEY, temperature=temperature)

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=temperature)


def get_llamaindex_llm(temperature: float = 0.1):
    """LlamaIndex LLM used for RAG/semantic-SQL answer synthesis (Settings.llm)."""
    if LLM_PROVIDER == "anthropic":
        from llama_index.llms.anthropic import Anthropic

        return Anthropic(model=ANTHROPIC_MODEL, api_key=ANTHROPIC_API_KEY, temperature=temperature)

    from llama_index.llms.openai import OpenAI

    return OpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=temperature)


def get_crewai_model_string() -> str:
    """LiteLLM-style 'provider/model' string for CrewAI's Agent(llm=...)."""
    if LLM_PROVIDER == "anthropic":
        return f"anthropic/{ANTHROPIC_MODEL}"
    return f"openai/{OPENAI_MODEL}"
