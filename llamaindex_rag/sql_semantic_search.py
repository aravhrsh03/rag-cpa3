"""
LlamaIndex Semantic SQL (NetworkAnalytics worker).

Connects to data/telecom_ops.db, builds an ObjectIndex over human-readable
descriptions of the analytics tables so a question can be semantically
matched to the right table(s), and exposes a SQLTableRetrieverQueryEngine
via a single `answer_network_analytics_question` function.

Per the project spec: LlamaIndex is used ONLY for retrieval/query
synthesis here - the query engine generates and runs the SQL itself, this
module never hand-writes business-data queries or caches rows in Python.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llama_index.core import SQLDatabase, Settings, VectorStoreIndex
from llama_index.core.objects import ObjectIndex, SQLTableNodeMapping, SQLTableSchema
from llama_index.core.query_engine import SQLTableRetrieverQueryEngine
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from sqlalchemy import create_engine

from config import DB_PATH, EMBEDDING_MODEL, get_llamaindex_llm

# Tables exposed to semantic SQL retrieval, per section 5.1/5.3 of the spec.
# open_incidents, billing_* tables are intentionally excluded here - they are
# read/written exclusively through the ADK agent tools, not through
# free-form generated SQL.
_TABLE_CONTEXTS = {
    "network_towers": (
        "Tower inventory. One row per cell tower: tower_id, tower_name, "
        "region (Midwest, Northeast, Southeast, Southwest, West), city, "
        "state, technology (4G LTE, 5G, 5G mmWave), operational status "
        "(OPERATIONAL, DEGRADED, OFFLINE, MAINTENANCE), coordinates, and "
        "commissioned_date. Use for questions about where towers are "
        "located, what technology they run, or their current status."
    ),
    "network_outages": (
        "Historical outage log, one row per past or ongoing regional "
        "outage: outage_id, region, severity (CRITICAL, MAJOR, MINOR), "
        "start_time, end_time, duration_hours, affected_customers, "
        "root_cause, status (RESOLVED, ONGOING), and a text description. "
        "Use for questions about how many/which outages happened, outage "
        "severity counts by region, longest or highest-impact outages, "
        "root causes, or SLA-credit-relevant outage duration and region. "
        "This is analytics history, not the live incident queue."
    ),
    "tower_performance": (
        "Time-series performance samples per tower: performance_id, "
        "tower_id, recorded_at, latency_ms, packet_loss_pct, "
        "downlink_throughput_mbps, uplink_throughput_mbps, "
        "signal_strength_dbm, active_connections. Each tower has multiple "
        "samples over time. Use for questions about current/latest "
        "latency, packet loss, throughput, or signal strength - always "
        "filter to the single latest recorded_at per tower rather than "
        "averaging across samples."
    ),
    "customer_subscriptions": (
        "Customer subscription/plan directory: subscription_id, "
        "customer_id, customer_name, account_type (Consumer, Business, "
        "Enterprise), plan_name, monthly_fee, region, city, state, status "
        "(ACTIVE, SUSPENDED, CANCELLED), line_count, start_date. Use for "
        "questions about which plans customers have, fees, account types, "
        "or subscription counts by region/plan."
    ),
}

_sql_database = None
_query_engine = None


_settings_configured = False


def _configure_settings() -> None:
    # Settings.embed_model has a lazy-resolving getter that, if read before
    # anything is assigned, tries to default to an OpenAI embedding model
    # (requiring a package we don't install). So assign unconditionally on
    # first use instead of checking the current value first.
    global _settings_configured
    if not _settings_configured:
        Settings.embed_model = HuggingFaceEmbedding(model_name=EMBEDDING_MODEL)
        _settings_configured = True
    Settings.llm = get_llamaindex_llm()


def _build_query_engine() -> SQLTableRetrieverQueryEngine:
    _configure_settings()

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"{DB_PATH} does not exist yet. Run `python init_db.py` from the "
            "project root first."
        )

    engine = create_engine(f"sqlite:///{DB_PATH}")
    sql_database = SQLDatabase(engine, include_tables=list(_TABLE_CONTEXTS.keys()))

    table_node_mapping = SQLTableNodeMapping(sql_database)
    table_schema_objs = [
        SQLTableSchema(table_name=table_name, context_str=context_str)
        for table_name, context_str in _TABLE_CONTEXTS.items()
    ]

    object_index = ObjectIndex.from_objects(
        table_schema_objs,
        table_node_mapping,
        VectorStoreIndex,
    )

    return SQLTableRetrieverQueryEngine(
        sql_database,
        object_index.as_retriever(similarity_top_k=2),
    )


def get_query_engine() -> SQLTableRetrieverQueryEngine:
    global _query_engine
    if _query_engine is None:
        _query_engine = _build_query_engine()
    return _query_engine


def answer_network_analytics_question(question: str) -> str:
    """
    Answers a natural-language analytics question by semantically selecting
    the right table(s) (towers, outages, performance, subscriptions),
    generating SQL against data/telecom_ops.db, and synthesizing a natural
    language answer from the results.

    Used for: outage counts/severity by region, packet loss / latency /
    throughput rankings (latest sample), tower inventory questions, and
    subscription/plan analytics.
    """
    try:
        engine = get_query_engine()
    except FileNotFoundError as exc:
        return f"NetworkAnalytics is unavailable: {exc}"

    try:
        response = engine.query(question)
    except Exception as exc:  # pragma: no cover - defensive, surfaced to UI
        return f"NetworkAnalytics failed to answer the question: {exc}"

    return str(response).strip()


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Which region had the most CRITICAL network outages?"
    print(f"Q: {q}\n")
    print(answer_network_analytics_question(q))
