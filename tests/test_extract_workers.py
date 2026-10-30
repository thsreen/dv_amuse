"""Bounded parallel extraction: same graph as sequential, honest traces, capped workers."""
import threading

import pytest

from conftest import dependency_handler, extraction_handler
from dv_agent.ingest.extract import MAX_WORKERS_CAP, ExtractConfig, default_max_workers
from dv_agent.core.llm import FakeLLM, LLMError
from dv_agent.pipeline import run_build_graph, run_ingest


def _normalized_graph(out):
    from dv_agent.graph.graph import load_graph
    from dv_agent.pipeline import GRAPH_FILE
    G = load_graph(out / GRAPH_FILE)
    drop = {"span_id", "response_id", "trace_id"}
    nodes = {n: {k: v for k, v in d.items() if k not in drop} for n, d in G.nodes(data=True)}
    edges = sorted((u, v, k, {a: b for a, b in d.items() if a not in drop})
                   for u, v, k, d in G.edges(keys=True, data=True))
    return nodes, edges


def _stats_equal(a, b):
    for section in ("requirements", "dependencies"):
        for key in ("requirements", "rejected", "entities", "groups", "edges"):
            assert a[section].get(key) == b[section].get(key), (section, key)
        assert a[section].get("failed_chunks", []) == b[section].get("failed_chunks", [])
        assert a[section].get("failed_groups", []) == b[section].get("failed_groups", [])


def test_parallel_build_matches_sequential(spec_repo, tmp_path):
    outs = []
    for workers in (1, MAX_WORKERS_CAP):
        out = tmp_path / f"run{workers}"
        llm = FakeLLM({"spec_requirements": extraction_handler,
                       "requirement_dependencies": dependency_handler})
        run_ingest(spec_repo, out)
        outs.append((out, run_build_graph(out, llm, ExtractConfig(max_workers=workers), mode="graph")))
    _stats_equal(outs[0][1], outs[1][1])
    assert _normalized_graph(outs[0][0]) == _normalized_graph(outs[1][0])


def test_parallel_failure_ordering_matches_sequential(spec_repo, tmp_path):
    def flaky(payload):
        if "Reload Register" in payload["text"]:
            raise LLMError("transient", "simulated")
        return extraction_handler(payload)

    outs = []
    for workers in (1, MAX_WORKERS_CAP):
        out = tmp_path / f"run{workers}"
        llm = FakeLLM({"spec_requirements": flaky,
                       "requirement_dependencies": dependency_handler})
        run_ingest(spec_repo, out)
        outs.append((out, run_build_graph(out, llm, ExtractConfig(max_workers=workers), mode="graph")))
    assert len(outs[0][1]["requirements"]["failed_chunks"]) == 1
    assert outs[0][1]["llm"]["status"] == outs[1][1]["llm"]["status"] == "BLOCKED"
    assert outs[0][1]["requirements"]["failed_chunks"] == outs[1][1]["requirements"]["failed_chunks"]
    for out, _ in outs:
        recovered = run_build_graph(out, FakeLLM({"spec_requirements": extraction_handler,
                                                  "requirement_dependencies": dependency_handler}), mode="graph")
        assert recovered["llm"]["status"] == "PASS"
    assert _normalized_graph(outs[0][0]) == _normalized_graph(outs[1][0])


def test_parallel_config_errors_still_abort(spec_repo, tmp_path):
    def denied(payload):
        raise LLMError("auth", "simulated")

    out = tmp_path / "run"
    llm = FakeLLM({"spec_requirements": denied, "requirement_dependencies": dependency_handler})
    run_ingest(spec_repo, out)
    result = run_build_graph(out, llm, ExtractConfig(max_workers=MAX_WORKERS_CAP), mode="graph")
    assert result["llm"]["status"] == "BLOCKED"


def test_workers_default_env_and_cap(monkeypatch):
    monkeypatch.delenv("DV_AGENT_MAX_WORKERS", raising=False)
    assert default_max_workers() == 1
    assert ExtractConfig().max_workers == 1
    monkeypatch.setenv("DV_AGENT_MAX_WORKERS", "3")
    assert ExtractConfig().max_workers == 3
    monkeypatch.setenv("DV_AGENT_MAX_WORKERS", "99")
    assert ExtractConfig().max_workers == MAX_WORKERS_CAP
    monkeypatch.setenv("DV_AGENT_MAX_WORKERS", "0")
    assert ExtractConfig().max_workers == 1
    monkeypatch.setenv("DV_AGENT_MAX_WORKERS", "many")
    with pytest.raises(ValueError):
        ExtractConfig()


def test_workers_flag_validation():
    from dv_agent.cli import UsageError, _extract_config
    assert _extract_config(None) is None
    assert _extract_config(2).max_workers == 2
    assert _extract_config(99).max_workers == MAX_WORKERS_CAP
    with pytest.raises(UsageError):
        _extract_config(0)


def test_fake_llm_ids_stay_unique_under_threads():
    llm = FakeLLM({"k": lambda payload: {}})
    seen, guard = [], threading.Lock()

    def call():
        result = llm.structured(name="k", instructions="i", payload={},
                                schema={"type": "object"})
        with guard:
            seen.append(result.response_id)

    threads = [threading.Thread(target=call) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(llm.calls) == 32 and len(set(seen)) == 32


def test_concurrent_spans_keep_parents_and_valid_jsonl(tmp_path):
    from dv_agent.core.trace import Tracer, read_trace
    sink = tmp_path / "t.jsonl"
    with Tracer(sink, "run") as tracer:
        with tracer.span("stage") as stage:
            def work(i):
                with tracer.span(f"child:{i}", _parent=stage.id) as span:
                    with tracer.span("llm:k", as_type="generation", _parent=span.id):
                        pass
            threads = [threading.Thread(target=work, args=(i,)) for i in range(16)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        assert tracer._stack == [tracer.root.id]
    records = read_trace(sink)
    by_id = {r["span_id"]: r for r in records}
    assert len(records) == 2 + 16 * 2  # root, stage, and one pair per thread
    for r in records:
        if r["name"].startswith("child:"):
            assert r["parent_id"] == by_id[r["parent_id"]]["span_id"]
            assert by_id[r["parent_id"]]["name"] == "stage"
        if r["name"] == "llm:k":
            assert by_id[r["parent_id"]]["name"].startswith("child:")
