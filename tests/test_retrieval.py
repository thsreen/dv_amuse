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


def test_evaluate_compares_variants_and_reports_misses(graph):
    from dataclasses import replace

    from dv_agent.retrieval.evaluate import Case, compare, format_table
    _, G = graph
    cases = [Case("reload value when counter reaches zero", ["RELOAD"], "paraphrase"),
             Case("zzzz qqqq unrelated words", ["Nowhere"], "adversarial")]
    base = RetrievalConfig()
    result = compare(G, cases, [1, 3], {"lexical": replace(base, ppr_weight=0.0), "graph": base})
    assert set(result["variants"]) == {"lexical", "graph"} and result["cases"] == 2
    graph_variant = result["variants"]["graph"]
    assert graph_variant["metrics"][3]["recall_at_k"] == 0.5
    assert graph_variant["recall_by_type"] == {"adversarial": 0.0, "paraphrase": 1.0}
    assert [m["query"] for m in graph_variant["misses"]] == ["zzzz qqqq unrelated words"]
    table = format_table(result)
    assert "| lexical |" in table and "recall@3" in table and "Labelled cases: 2" in table


def test_evaluate_cli_reports_a_table(graph, tmp_path, capsys):
    import json

    from dv_agent.cli import main
    out, _ = graph
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([{"query": "reload value when counter reaches zero",
                                  "relevant_sections": ["RELOAD"], "type": "lexical"}]))
    assert main(["evaluate", "--out", str(out), "--cases", str(cases), "--k", "1", "3", "--ablate", "--table"]) in (0, None)
    text = capsys.readouterr().out
    assert "lexical only (BM25)" in text and "graph retrieval" in text and "recall@1" in text
