"""
Stage 1: shared configuration (config.py).

This is the first thing every other module imports, so it's the first thing
worth being able to run and trust on its own.

    pytest tests/test_01_config.py -v
"""
import config


def test_paths_resolve_under_project_root():
    assert config.DATA_DIR == config.PROJECT_ROOT / "data"
    assert config.DOCUMENTS_DIR == config.DATA_DIR / "documents"
    assert config.VECTOR_INDEX_DIR == config.DATA_DIR / "vector_index"
    assert config.SCHEMA_SQL_PATH.name == "01_schema.sql"
    assert config.SEED_SQL_PATH.name == "02_seed_data.sql"


def test_llm_provider_is_a_supported_value():
    assert config.LLM_PROVIDER in ("anthropic", "openai")


def test_billing_auto_approval_limit_matches_policy():
    # Mirrors billing_disputes_policy.txt / 01_schema.sql: <=$50 auto-approves.
    assert config.BILLING_AUTO_APPROVAL_LIMIT == 50.00


def test_get_crewai_model_string_matches_llm_provider():
    model_string = config.get_crewai_model_string()
    if config.LLM_PROVIDER == "anthropic":
        assert model_string == f"anthropic/{config.ANTHROPIC_MODEL}"
    else:
        assert model_string == f"openai/{config.OPENAI_MODEL}"


def test_get_adk_model_wraps_provider_slash_model_in_litellm(monkeypatch):
    from google.adk.models.lite_llm import LiteLlm

    monkeypatch.setattr(config, "ADK_MODEL", "anthropic/claude-haiku-4-5-20251001")
    assert isinstance(config.get_adk_model(), LiteLlm)


def test_get_adk_model_passes_bare_model_id_through(monkeypatch):
    monkeypatch.setattr(config, "ADK_MODEL", "gemini-2.0-flash")
    assert config.get_adk_model() == "gemini-2.0-flash"
