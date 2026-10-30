import json

import pytest

from conftest import dependency_handler, extraction_handler, plan_handler, rerank_handler
from dv_agent.graph.community import build_communities  # noqa: F401  (import check)
from dv_agent.retrieval.dense import HashEmbedder, load_index
from dv_agent.retrieval.evaluate import Case, evaluate
from dv_agent.graph.graph import lineage, load_graph
from dv_agent.core.llm import FakeLLM
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_query, run_test_plan
from dv_agent.plan.planning import PlanConfig, iterative_retrieve
from dv_agent.retrieval.retrieval import RetrievalConfig, layered_view
from dv_agent.core.trace import Tracer, read_trace


def _full_llm():
    return FakeLLM({"spec_requirements": extraction_handler, "requirement_dependencies": dependency_handler,
                    "rerank_chunks": rerank_handler, "test_plan_items": plan_handler})


def _graph(spec_repo, tmp_path, llm, embedder=None):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, llm, embedder=embedder, mode="graph")
    return out


def _req(G, prefix):
    return next(n for n, d in G.nodes(data=True)
                if d.get("type") == "requirement" and d["statement"].startswith(prefix))


def test_communities_are_navigation_only(spec_repo, tmp_path):
    out = _graph(spec_repo, tmp_path, _full_llm())
    G = load_graph(out / GRAPH_FILE)
    coms = [n for n, d in G.nodes(data=True) if d.get("type") == "community"]
    assert coms
    for c in coms:
        assert G.nodes[c]["layer"] == 3 and G.nodes[c]["navigation_only"] and G.nodes[c]["label"]
        assert all(G.nodes[m]["type"] in ("requirement", "entity") for m in G.nodes[c]["members"])
    assert {e[2] for e in G.in_edges(coms[0], keys=True)} == {"MEMBER_OF"}


def test_hybrid_query_uses_dense_index(spec_repo, tmp_path):
    emb = HashEmbedder(dim=256)
    out = _graph(spec_repo, tmp_path, _full_llm(), embedder=emb)
    stats = json.loads((out / "build_stats.json").read_text())
    assert stats["dense"]["status"] == "PASS" and stats["dense"]["dim"] == 256
    model, ids, matrix = load_index(out / "dense")
    assert model == emb.model and len(ids) == matrix.shape[0]
    result = run_query(out, "reload value loads when counter reaches zero", embedder=emb)
    assert result["dense"] == "PASS"
    top = result["evidence"][0]
    assert top["components"]["dense"] > 0
    assert top["section"].endswith("2.2 Reload Register (RELOAD)")


def test_dense_index_model_mismatch_is_refused(spec_repo, tmp_path):
    out = _graph(spec_repo, tmp_path, _full_llm(), embedder=HashEmbedder(dim=256))
    with pytest.raises(ValueError):
        run_query(out, "reload", embedder=HashEmbedder(dim=128))


def test_multi_hop_expands_along_dependencies_until_sufficient(spec_repo, tmp_path):
    out = _graph(spec_repo, tmp_path, _full_llm())
    G = load_graph(out / GRAPH_FILE)
    tracer_sink = tmp_path / "t.jsonl"
    cfg = PlanConfig(retrieval=RetrievalConfig())
    with Tracer(tracer_sink, "t") as tracer:
        llm = _full_llm()
        ev = iterative_retrieve(G, layered_view(G), "counter reload value when it reaches zero",
                                llm, tracer, cfg)
    assert len(ev["trail"]) == 2
    first, second = ev["trail"]
    assert first["sufficient"] is False and first["missing"] == "Enable bit semantics"
    assert second["query"].endswith("Enable bit semantics") and second["expansion_seeds"]
    assert second["sufficient"] is True and ev["sufficient"] is True
    assert ev["selected_chunks"]


def test_test_plan_items_are_cited_recorded_and_review_gated(spec_repo, tmp_path):
    out = _graph(spec_repo, tmp_path, _full_llm())
    G = load_graph(out / GRAPH_FILE)
    req = _req(G, "On reaching zero")
    cfg = PlanConfig(retrieval=RetrievalConfig())
    plan = run_test_plan(out, [req], _full_llm(), cfg)
    items = [i for i in plan["items"] if "id" in i]
    assert len(items) == 1, "item citing an unknown requirement must be rejected"
    item = items[0]
    assert item["review_status"] == "NEEDS_REVIEW" and item["requirement"] == req
    H = load_graph(out / GRAPH_FILE)
    node = H.nodes[item["id"]]
    assert node["type"] == "test_plan_item" and node["trace_id"] == plan["trace_id"]
    lin = lineage(H, item["id"])
    assert req in {f["req_id"] for f in lin["facts"]}
    assert {s["chunk_id"] for s in lin["sources"]} == set(item["cited_chunk_ids"])
    spans = [r for r in read_trace(out / "trace.jsonl", plan["trace_id"]) if r["name"] == f"lineage:{item['id']}"]
    assert spans and req in spans[0]["metadata"]["fact_ids"]
    assert (out / "test_plan.json").exists()


def test_evaluation_reports_recall_and_mrr(spec_repo, tmp_path):
    out = _graph(spec_repo, tmp_path, _full_llm())
    G = load_graph(out / GRAPH_FILE)
    cases = [Case("reload value when counter reaches zero", ["RELOAD"]),
             Case("interrupt asserted until STATUS bit written", ["Interrupts"]),
             Case("counter decrements on every clock when enable set", ["CTRL"])]
    metrics = evaluate(G, cases, k=3)
    assert metrics["cases"] == 3 and metrics["dense"] == "NOT_RUN"
    assert metrics["recall_at_k"] == 1.0
    assert 0.0 < metrics["mrr"] <= 1.0
