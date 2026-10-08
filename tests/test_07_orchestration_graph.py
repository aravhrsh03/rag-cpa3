"""
Stage 7: LangGraph supervisor + worker graph wiring (orchestration/graph.py).

Confirms the graph compiles and is wired the way the spec requires, without
actually invoking it - a real run needs a live LLM call for the supervisor's
routing decision (see HOW_TO_RUN.md for the manual walkthrough scenarios).

    pytest tests/test_07_orchestration_graph.py -v
"""
from orchestration.graph import build_graph
from orchestration.state import WORKERS


def test_build_graph_compiles():
    graph = build_graph()
    assert graph is not None


def test_graph_has_a_node_for_every_worker_and_the_supervisor():
    graph = build_graph()
    node_names = set(graph.get_graph().nodes)
    assert node_names.issuperset({"supervisor", *WORKERS})
