"""
Stage 8: LlamaIndex RAG/semantic-SQL error handling
(llamaindex_rag/document_rag.py, llamaindex_rag/sql_semantic_search.py).

Only exercises the "index/database isn't ready" paths, which run fully
offline (the embedding model and LLM settings are stubbed out). The real
retrieval path needs the policy documents indexed and a configured LLM key -
that's the manual walkthrough in HOW_TO_RUN.md, not this automated suite.

    pytest tests/test_08_rag_error_paths.py -v
"""


def test_answer_policy_question_reports_missing_documents(tmp_path, monkeypatch):
    from llamaindex_rag import document_rag

    monkeypatch.setattr(document_rag, "_configure_settings", lambda: None)
    monkeypatch.setattr(document_rag, "DOCUMENTS_DIR", tmp_path / "documents")
    monkeypatch.setattr(document_rag, "VECTOR_INDEX_DIR", tmp_path / "vector_index")
    monkeypatch.setattr(document_rag, "_index", None)
    monkeypatch.setattr(document_rag, "_query_engine", None)

    result = document_rag.answer_policy_question("What is the roaming policy?")
    assert result.startswith("PolicyRAG is unavailable")


def test_answer_network_analytics_question_reports_missing_database(tmp_path, monkeypatch):
    from llamaindex_rag import sql_semantic_search

    monkeypatch.setattr(sql_semantic_search, "_configure_settings", lambda: None)
    monkeypatch.setattr(sql_semantic_search, "DB_PATH", tmp_path / "does_not_exist.db")
    monkeypatch.setattr(sql_semantic_search, "_query_engine", None)

    result = sql_semantic_search.answer_network_analytics_question("Which region had the most outages?")
    assert result.startswith("NetworkAnalytics is unavailable")
