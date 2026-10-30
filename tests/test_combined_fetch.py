import networkx as nx
import pytest

from dv_agent.retrieval.combined_fetch import SOURCE_TYPES, adaptive_select, combined_fetch, step_targets, target_paths
from dv_agent.graph.graph import load_graph
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_testplan_doc
from dv_agent.retrieval.retrieval import layered_view
from dv_agent.core.trace import read_trace
from test_testplan_doc import _llm


@pytest.fixture
def built(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(), mode="graph")
    return out, load_graph(out / GRAPH_FILE)


def test_target_paths_are_shortest_and_bounded():
    H = nx.Graph()
    for u, v in ("ab", "bc", "cd", "de", "bd"):
        H.add_edge(u, v, weight=0.8, type="X")
    paths = target_paths(H, ["a"], ["e", "c", "zz"], max_targets=5, max_length=4)
    assert [(p["target"], p["path"]) for p in paths] == [("c", ["a", "b", "c"]), ("e", ["a", "b", "d", "e"])]
    assert target_paths(H, ["a"], ["e"], max_targets=5, max_length=3) == []


def test_adaptive_select_keeps_every_source_and_the_cap():
    cands = {"retrieval": [dict(req_id=f"R{i}", score=1.0 - i / 100, via="r") for i in range(10)],
             "path": [dict(req_id="P1", score=0.2, via="p"), dict(req_id="R0", score=0.1, via="p")],
             "coverage": [dict(req_id="C1", score=0.3, via="c")]}
    picked = adaptive_select(cands, "req_id", limit=5, min_per_source=2)
    ids = [p["req_id"] for p in picked]
    assert len(ids) == 5 and "P1" in ids and "C1" in ids
    r0 = next(p for p in picked if p["req_id"] == "R0")
    assert r0["source"] == "retrieval" and r0["sources"] == ["retrieval", "path"]


def test_step_targets_map_verified_signals_and_registers(built):
    _, G = built
    interfaces = {"groups": [{"signals": [{"name": "IRQ"}, {"name": "NOT_IN_GRAPH"}]}]}
    registers = {"registers": [{"abbreviation": "CTRL", "name": "Control Register"}]}
    assert {G.nodes[t]["name"] for t in step_targets(G, interfaces, registers)} == {"IRQ", "Control Register (CTRL)"}


def test_combined_fetch_merges_sources_deterministically(built):
    _, G = built
    reqs = sorted(n for n, d in G.nodes(data=True) if d.get("type") == "requirement")
    targets = step_targets(G, {"groups": [{"signals": [{"name": "IRQ"}]}]},
                           {"registers": [{"abbreviation": "CTRL", "name": "Control Register"}]})
    kw = dict(H=layered_view(G), targets=targets, covered_req_ids={reqs[0]}, covered_chunk_ids=set())
    a = combined_fetch(G, "counter reload when it reaches zero", **kw)
    assert a == combined_fetch(G, "counter reload when it reaches zero", **kw)
    assert sum(1 for v in a["selection"].values() if v) >= 2 and set(a["selection"]) == set(SOURCE_TYPES)
    assert all(r["sources"] and r["via"] for r in a["requirements"])
    assert a["paths"] and all(" -> " in p["path"] for p in a["paths"])
    assert reqs[0] not in a["coverage_targets"] and set(a["coverage_targets"]) <= set(a["path_targets"])


def test_testplan_sections_fetch_with_step_targets(built):
    out, _ = built
    summary = run_testplan_doc(out, _llm(), mode="graph")
    spans = [r for r in read_trace(out / "trace.jsonl", summary["trace_id"]) if r["name"] == "fetch_context"]
    assert any(s["input"]["targets"] > 0 for s in spans)
    assert any(any(s["input"]["selection"].get(t) for t in ("path", "coverage")) for s in spans)
