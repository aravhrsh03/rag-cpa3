"""
LlamaIndex Document RAG (PolicyRAG worker).

Builds a VectorStoreIndex over the six policy TXT files in data/documents/
using a local HuggingFace embedding model, persists it to data/vector_index/
so it is only built once, and exposes a single function -
`answer_policy_question` - that a LangGraph node calls with a natural
language question and gets back a synthesized string answer.

Per the project spec: LlamaIndex is used ONLY for retrieval (as_query_engine).
No LlamaIndex agents, workflows, or ReAct patterns are used here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llama_index.core import (
    Settings,
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from config import DOCUMENTS_DIR, EMBEDDING_MODEL, VECTOR_INDEX_DIR, get_llamaindex_llm

_index = None
_query_engine = None


_settings_configured = False


def _configure_settings() -> None:
    """Point LlamaIndex's global Settings at our local embedder + the
    configured LLM provider (Anthropic or OpenAI - see config.LLM_PROVIDER).

    Note: Settings.embed_model has a lazy-resolving getter that, if read
    before anything is assigned, tries to default to an OpenAI embedding
    model (requiring a package we don't install). So we assign unconditionally
    on first use instead of checking the current value first.
    """
    global _settings_configured
    if not _settings_configured:
        Settings.embed_model = HuggingFaceEmbedding(model_name=EMBEDDING_MODEL)
        _settings_configured = True
    Settings.llm = get_llamaindex_llm()


def _build_or_load_index() -> VectorStoreIndex:
    _configure_settings()

    has_persisted_index = VECTOR_INDEX_DIR.exists() and any(VECTOR_INDEX_DIR.iterdir())
    if has_persisted_index:
        storage_context = StorageContext.from_defaults(persist_dir=str(VECTOR_INDEX_DIR))
        return load_index_from_storage(storage_context)

    if not DOCUMENTS_DIR.exists() or not any(DOCUMENTS_DIR.glob("*.txt")):
        raise FileNotFoundError(
            f"No policy documents found in {DOCUMENTS_DIR}. Expected the six "
            "provided *.txt policy files."
        )

    documents = SimpleDirectoryReader(str(DOCUMENTS_DIR)).load_data()
    index = VectorStoreIndex.from_documents(documents)
    VECTOR_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    index.storage_context.persist(persist_dir=str(VECTOR_INDEX_DIR))
    return index


def get_query_engine():
    """Lazily builds/loads the index and query engine exactly once per process."""
    global _index, _query_engine
    if _query_engine is None:
        _index = _build_or_load_index()
        _query_engine = _index.as_query_engine(similarity_top_k=4)
    return _query_engine


def answer_policy_question(question: str) -> str:
    """
    Answers a natural-language policy/FAQ question by retrieving the most
    relevant chunks from the policy TXT files and synthesizing an answer.

    Used for: roaming, SLA/outage credit eligibility, billing dispute rules,
    network outage classification, 5G FAQ, and device upgrade policy
    questions.
    """
    try:
        engine = get_query_engine()
    except FileNotFoundError as exc:
        return f"PolicyRAG is unavailable: {exc}"

    try:
        response = engine.query(question)
    except Exception as exc:  # pragma: no cover - defensive, surfaced to UI
        return f"PolicyRAG failed to answer the question: {exc}"

    return str(response).strip()


if __name__ == "__main__":
    # Quick manual smoke test: python llamaindex_rag/document_rag.py "question"
    q = " ".join(sys.argv[1:]) or "What is Prodapt's roaming policy for Western Europe?"
    print(f"Q: {q}\n")
    print(answer_policy_question(q))
