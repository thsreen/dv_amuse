"""Regression tests for defects found in the code review."""
import json

import pytest

from conftest import PAGES, dependency_handler, extraction_handler, plan_handler, rerank_handler
from dv_agent.cli import main
from dv_agent.retrieval.dense import HashEmbedder, MetaEmbedder
from dv_agent.retrieval.evaluate import Case, evaluate
from dv_agent.graph.graph import load_graph
from dv_agent.ingest.ingest import discover
from dv_agent.core.llm import FakeLLM, LLMError
from dv_agent.pipeline import GRAPH_FILE, clear_run, run_build_graph, run_ingest, run_query, run_test_plan
from dv_agent.plan.planning import PlanConfig
from dv_agent.retrieval.retrieval import RetrievalConfig, retrieve


def _llm(**overrides):
    handlers = {"spec_requirements": extraction_handler, "requirement_dependencies": dependency_handler,
                "rerank_chunks": rerank_handler, "test_plan_items": plan_handler}
    handlers.update(overrides)
    return FakeLLM(handlers)


def _built(spec_repo, tmp_path, llm=None):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, llm or _llm(), mode="graph")
    return out


def _reqs(out):
    G = load_graph(out / GRAPH_FILE)
    return G, sorted(n for n, d in G.nodes(data=True) if d.get("type") == "requirement")


def test_two_disconnected_documents_do_not_crash_retrieval(spec_repo, tmp_path):
    other = spec_repo / "doc" / "gpio_spec.txt"
    other.write_text("1 Overview\nThe GPIO block drives sixteen pins.\n\n2 Pins\nEach pin has a direction bit.\n")
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, None, mode="graph")
    G = load_graph(out / GRAPH_FILE)
    result = retrieve(G, "direction bit for each GPIO pin", RetrievalConfig(top_k=20))
    assert result["evidence"] and result["evidence"][0]["doc_path"].endswith("gpio_spec.txt")
    assert all(e["path"] for e in result["evidence"])


def test_unknown_extra_seed_is_ignored(spec_repo, tmp_path):
    out = _built(spec_repo, tmp_path)
    G = load_graph(out / GRAPH_FILE)
    assert retrieve(G, "reload", extra_seeds={"REQ-not-in-graph": 1.0})["evidence"]


def test_build_with_failed_chunks_is_not_reused(spec_repo, tmp_path):
    def flaky(payload):
        if "Reload Register" in payload["text"]:
            raise LLMError("transient", "simulated")
        return extraction_handler(payload)
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    first = run_build_graph(out, _llm(spec_requirements=flaky), mode="graph")
    assert first["requirements"]["failed_chunks"]
    assert run_build_graph(out, _llm(), mode="graph")["reused"] is False


def test_model_change_invalidates_build(spec_repo, tmp_path):
    out = _built(spec_repo, tmp_path)
    other = _llm()
    other.model = "other-model"
    assert run_build_graph(out, other, mode="graph")["reused"] is False


def test_embedder_change_invalidates_build_and_removes_stale_index(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(), embedder=HashEmbedder(dim=128), mode="graph")
    assert run_build_graph(out, _llm(), embedder=HashEmbedder(dim=64), mode="graph")["reused"] is False
    run_build_graph(out, _llm(), force=True, mode="graph")
    assert not (out / "dense").exists()


def test_replan_replaces_items_instead_of_accumulating(spec_repo, tmp_path):
    out = _built(spec_repo, tmp_path)
    _, reqs = _reqs(out)
    cfg = PlanConfig(retrieval=RetrievalConfig())
    run_test_plan(out, reqs[:1], _llm(), cfg)

    def other_plan(payload):
        data = plan_handler(payload)
        data["items"][0]["objective"] = "A different objective"
        return data
    run_test_plan(out, reqs[:1], _llm(test_plan_items=other_plan), cfg, force=True)
    G = load_graph(out / GRAPH_FILE)
    tps = [n for n, d in G.nodes(data=True) if d.get("type") == "test_plan_item"]
    assert len(tps) == 1 and "A different objective" in G.nodes[tps[0]]["content"]


def test_plan_always_offers_the_requirements_own_chunk(spec_repo, tmp_path):
    out = _built(spec_repo, tmp_path)
    G, reqs = _reqs(out)
    seen = {}

    def no_relevance(payload):
        return {"judgements": [{"chunk_id": c["chunk_id"], "relevance": 0} for c in payload["chunks"]],
                "sufficient": False, "missing": ""}

    def capture(payload):
        seen.update(payload)
        return plan_handler(payload)
    req = reqs[0]
    run_test_plan(out, [req], _llm(rerank_chunks=no_relevance, test_plan_items=capture),
                  PlanConfig(retrieval=RetrievalConfig()))
    assert [c["chunk_id"] for c in seen["chunks"]] == [G.nodes[req]["chunk_id"]]
    assert seen["evidence_judged_sufficient"] is False


def test_unknown_requirement_is_rejected_cleanly(spec_repo, tmp_path, capsys, monkeypatch):
    out = _built(spec_repo, tmp_path)
    with pytest.raises(KeyError):
        run_test_plan(out, ["REQ-missing"], _llm(), PlanConfig(retrieval=RetrievalConfig()))
    from dv_agent import cli
    monkeypatch.setattr(cli, "_llm", _llm)
    assert main(["plan", "REQ-missing", "--out", str(out)]) == 2
    assert "unknown requirement" in capsys.readouterr().err


def test_clear_run_refuses_unrelated_directory(tmp_path):
    victim = tmp_path / "project"
    (victim / "text").mkdir(parents=True)
    (victim / "text" / "notes.txt").write_text("keep")
    with pytest.raises(ValueError):
        clear_run(victim)
    assert (victim / "text" / "notes.txt").exists()


def test_cli_reports_missing_stage_inputs(tmp_path, capsys):
    assert main(["query", "anything", "--out", str(tmp_path / "nowhere")]) == 2
    assert "run the earlier stage first" in capsys.readouterr().err


def test_corrupt_cache_entry_is_refetched(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    llm = _llm()
    llm.cache_dir = out / "llm_cache"
    run_build_graph(out, llm, mode="graph")
    entry = next((out / "llm_cache").glob("*.json"))
    entry.write_text("{truncated")
    again = _llm()
    again.cache_dir = out / "llm_cache"
    run_build_graph(out, again, force=True, mode="graph")
    assert again.calls and json.loads(entry.read_text())["data"]


def test_discover_does_not_descend_into_skipped_dirs(spec_repo):
    (spec_repo / "node_modules" / "doc").mkdir(parents=True)
    (spec_repo / "node_modules" / "doc" / "x.md").write_text("# x\n")
    assert not any(d.path.startswith("node_modules") for d in discover(spec_repo))


def test_evaluate_k_larger_than_top_k(spec_repo, tmp_path):
    out = _built(spec_repo, tmp_path)
    G = load_graph(out / GRAPH_FILE)
    metrics = evaluate(G, [Case("STATUS bit 0 IRQ", ["3 Interrupts"])], k=12,
                       cfg=RetrievalConfig(top_k=1, ppr_weight=5.0))
    assert metrics["rows"][0]["rank"] is not None


def test_meta_embedder_empty_input():
    emb = MetaEmbedder(model="m", api_key="k", client=object())
    assert emb.embed([]).shape[0] == 0


def test_duplicate_quote_in_one_chunk_counted_once(spec_repo, tmp_path):
    def dup(payload):
        data = extraction_handler(payload)
        if data["requirements"]:
            data["requirements"].append(dict(data["requirements"][0], statement="Same quote again"))
        return data
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    stats = run_build_graph(out, _llm(spec_requirements=dup), mode="graph")
    assert stats["requirements"]["requirements"] == 4
