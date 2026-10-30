from conftest import dependency_handler, extraction_handler, plan_handler, rerank_handler
from dv_agent.core.llm import FakeLLM
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_test_plan
from dv_agent.plan.planning import PlanConfig
from dv_agent.retrieval.retrieval import RetrievalConfig


def _llm():
    return FakeLLM({"spec_requirements": extraction_handler, "requirement_dependencies": dependency_handler,
                    "rerank_chunks": rerank_handler, "test_plan_items": plan_handler})


def _req_ids(out):
    import json
    G = json.loads((out / GRAPH_FILE).read_text())
    return [n["id"] for n in G["nodes"] if n.get("type") == "requirement"]


def test_ingest_is_reused_until_sources_change(spec_repo, tmp_path):
    out = tmp_path / "run"
    assert run_ingest(spec_repo, out)["reused"] is False
    assert run_ingest(spec_repo, out)["reused"] is True
    assert run_ingest(spec_repo, out, force=True)["reused"] is False
    (spec_repo / "doc" / "tmr32_spec.txt").write_text("changed\f" + "x" * 500)
    assert run_ingest(spec_repo, out)["reused"] is False


def test_changing_include_selection_forces_reingest(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    assert run_ingest(spec_repo, out, include=["doc/*.txt"])["reused"] is False


def test_reingest_invalidates_graph_and_plan(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(), mode="graph")
    assert (out / GRAPH_FILE).exists()
    (spec_repo / "doc" / "tmr32_spec.txt").write_text("changed\f" + "x" * 500)
    run_ingest(spec_repo, out)
    assert not (out / GRAPH_FILE).exists() and not (out / "build_stats.json").exists()


def test_graph_build_reused_with_zero_llm_calls(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    first_llm = _llm()
    first = run_build_graph(out, first_llm, mode="graph")
    assert first["reused"] is False and first_llm.calls
    second_llm = _llm()
    second = run_build_graph(out, second_llm, mode="graph")
    assert second["reused"] is True and second_llm.calls == []
    assert second["nodes"] == first["nodes"]


def test_force_rebuilds_graph(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(), mode="graph")
    forced_llm = _llm()
    forced = run_build_graph(out, forced_llm, force=True, mode="graph")
    assert forced["reused"] is False and not forced_llm.calls  # rebuild from durable batches


def test_structural_build_is_not_reused_for_llm_build(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, None, mode="graph")
    llm_build = run_build_graph(out, _llm(), mode="graph")
    assert llm_build["reused"] is False and llm_build["mode"] == "llm:fake-llm"


def test_test_plan_reused_unless_forced(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(), mode="graph")
    req = _req_ids(out)[0]
    cfg = PlanConfig(retrieval=RetrievalConfig())
    first = run_test_plan(out, [req], _llm(), cfg)
    assert first["reused"] is False
    llm = _llm()
    second = run_test_plan(out, [req], llm, cfg)
    assert second["reused"] is True and llm.calls == []
    assert run_test_plan(out, [req], _llm(), cfg, force=True)["reused"] is False


def test_clear_run_removes_only_known_artifacts(spec_repo, tmp_path):
    from dv_agent.pipeline import clear_run
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    llm = _llm()
    llm.cache_dir = out / "llm_cache"
    run_build_graph(out, llm, mode="graph")
    (out / "keep_me.txt").write_text("user file")
    removed = clear_run(out)
    assert "graph.json" in removed and "llm_cache" in removed and "trace.jsonl" in removed
    assert (out / "keep_me.txt").exists()
    assert not (out / "graph.json").exists() and not (out / "llm_cache").exists()


def test_pipeline_fresh_clears_cache_and_reruns_every_stage(spec_repo, tmp_path, capsys):
    import json
    from dv_agent.cli import main
    out = tmp_path / "run"
    assert main(["pipeline", str(spec_repo), "--out", str(out)]) == 0
    capsys.readouterr()
    main(["pipeline", str(spec_repo), "--out", str(out)])
    again = json.loads(capsys.readouterr().out)
    assert again["ingest"]["reused"] and again["build"]["reused"]
    main(["pipeline", str(spec_repo), "--out", str(out), "--fresh"])
    fresh = json.loads(capsys.readouterr().out)
    assert fresh["cleared"] and not fresh["ingest"]["reused"] and not fresh["build"]["reused"]


def test_build_graph_fresh_deletes_llm_cache_and_calls_model_again(spec_repo, tmp_path, monkeypatch):
    from dv_agent import cli
    from dv_agent.pipeline import clear_llm_cache
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    llm = _llm()
    llm.cache_dir = out / "llm_cache"
    run_build_graph(out, llm, mode="graph")
    assert (out / "llm_cache").is_dir() and clear_llm_cache(out)
    assert not (out / "llm_cache").exists()
    monkeypatch.setattr(cli, "_llm", lambda: _cache_llm(out))
    assert cli.main(["build-graph", "--out", str(out), "--fresh"]) == 0


def _cache_llm(out):
    llm = _llm()
    llm.cache_dir = out / "llm_cache"
    return llm
