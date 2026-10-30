import pytest

from dv_agent.graph.graph import load_graph
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_query
from dv_agent.retrieval.retrieval import RetrievalConfig, retrieve


@pytest.fixture
def graph(spec_repo, tmp_path, fake_llm):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, fake_llm, mode="graph")
    return out, load_graph(out / GRAPH_FILE)


def test_query_ranks_relevant_chunk_with_explained_path(graph):
    _, G = graph
    result = retrieve(G, "counter reload value when it reaches zero")
    top = result["evidence"][0]
    assert top["section"].endswith("2.2 Reload Register (RELOAD)")
    assert top["explanation"].startswith("seed ") and "score" in top["explanation"]
    assert top["supporting_requirements"]
    assert all(e["path"][0].get("seed") for e in result["evidence"])


def test_walk_reaches_dependency_context(graph):
    _, G = graph
    result = retrieve(G, "RELOAD value loaded at zero", RetrievalConfig(top_k=10))
    sections = [e["section"] for e in result["evidence"]]
    assert any(s.endswith("2.1 Control Register (CTRL)") for s in sections)


def test_retrieval_is_deterministic_and_handles_no_match(graph):
    _, G = graph
    assert retrieve(G, "IRQ asserted") == retrieve(G, "IRQ asserted")
    assert retrieve(G, "zzzz qqqq")["evidence"] == []


def test_run_query_is_traced(graph):
    out, _ = graph
    result = run_query(out, "IRQ asserted until software writes")
    assert result["trace_id"] and result["evidence"]
    assert result["langfuse"] is False
