import json

import pytest

from conftest import dependency_handler, extraction_handler
from dv_agent.cli import main
from dv_agent.graph import load_graph
from dv_agent.graph_fetch import (dependency_closure, dependency_order, entity_context, global_fetch,
                                  requirement_coverage, resolve_entities)
from dv_agent.llm import FakeLLM
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_testplan_doc
from dv_agent.testplan_context import BUNDLE_SCHEMA_VERSION, fetch_context
from test_entity_ownership import owned_fields
from test_testplan_doc import _llm, entries_handler


def _build(spec_repo, tmp_path, llm):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    stats = run_build_graph(out, llm)
    return out, stats, load_graph(out / GRAPH_FILE)


def _ent(G, name, parent=""):
    return next(n for n, d in G.nodes(data=True) if d.get("type") == "entity" and d["name"] == name
                and d.get("parent", "") == parent)


def _req(G, prefix):
    return next(n for n, d in G.nodes(data=True) if d.get("type") == "requirement" and d["statement"].startswith(prefix))


@pytest.fixture
def owned(spec_repo, tmp_path):
    return _build(spec_repo, tmp_path, FakeLLM({"spec_requirements": owned_fields,
                                                "requirement_dependencies": dependency_handler}))


def test_owner_edges_link_registers_to_their_fields(owned):
    _, stats, G = owned
    ctrl, ctrl_en = _ent(G, "Control Register (CTRL)"), _ent(G, "Enable", "Control Register (CTRL)")
    assert G.has_edge(ctrl, ctrl_en, key="HAS_PART")
    assert stats["owners"]["owner_edges"] == 2
    assert [u["parent"] for u in stats["owners"]["unresolved_parents"]] == ["Status Register (STATUS)"]


def test_owned_names_resolve_only_with_their_owner(owned):
    _, _, G = owned
    names = {(G.nodes[a["entity_id"]]["name"], G.nodes[a["entity_id"]].get("parent", ""))
             for a in resolve_entities(G, "CTRL Enable bit behaviour")}
    assert ("Enable", "Control Register (CTRL)") in names and ("Control Register (CTRL)", "") in names
    assert ("Enable", "Reload Register (RELOAD)") not in names
    assert not any(G.nodes[a["entity_id"]]["name"] == "Enable" for a in resolve_entities(G, "the Enable bit"))


def test_entity_context_walks_parts_and_records_how(owned):
    _, _, G = owned
    ctx = entity_context(G, [_ent(G, "Control Register (CTRL)")])
    assert [p["name"] for p in ctx["parts"]] == ["Enable"]
    via = {r["req_id"]: r["via"] for r in ctx["requirements"]}
    rid = _req(G, "CTRL Enable makes")
    assert via[rid] == "mentions part Enable" and ctx["chunks"]


@pytest.fixture
def built(spec_repo, tmp_path):
    return _build(spec_repo, tmp_path, _llm())


def test_dependency_closure_and_order(built):
    _, _, G = built
    reload_id, enable_id = _req(G, "On reaching zero"), _req(G, "When CTRL.Enable")
    closure = dependency_closure(G, [reload_id])
    assert [(c["req_id"], c["depth"], c["root"]) for c in closure] == [(enable_id, 1, reload_id)]
    order = dependency_order(G, [reload_id])
    assert order["order"].index(enable_id) < order["order"].index(reload_id) and order["cycles"] == []


def cyclic_dependencies(payload):
    data = dependency_handler(payload)
    ids = {r["statement"]: r["req_id"] for r in payload["requirements"]}
    reload_id = next((v for k, v in ids.items() if k.startswith("On reaching zero")), None)
    enable_id = next((v for k, v in ids.items() if k.startswith("When CTRL.Enable")), None)
    if reload_id and enable_id:
        data["edges"].append({"src": enable_id, "dst": reload_id, "type": "DEPENDS_ON",
                              "rationale": "circular", "evidence_quote": "the counter decrements"})
    return data


def test_cycles_are_detected_and_raised_to_designers(spec_repo, tmp_path):
    out, _, G = _build(spec_repo, tmp_path, _llm(requirement_dependencies=cyclic_dependencies))
    order = dependency_order(G, [_req(G, "On reaching zero")])
    assert order["cycles"] == [sorted([_req(G, "On reaching zero"), _req(G, "When CTRL.Enable")])]
    run_testplan_doc(out, _llm())
    doc = json.loads((out / "testplan_doc.json").read_text())
    questions = next(s for s in doc["sections"] if s["id"] == "questions")["entries"]
    assert any(q["text"].startswith("These requirements depend on each other in a cycle") for q in questions)


def test_global_fetch_ranks_communities_and_expands(built):
    _, _, G = built
    res = global_fetch(G, "counter reload", top=2)
    assert res["communities"] and all(c["navigation_only"] for c in res["communities"])
    assert res["requirements"] and all(r["via"] for r in res["requirements"]) and res["chunks"]


def test_requirement_coverage_classes(built):
    _, _, G = built
    reload_id, enable_id = _req(G, "On reaching zero"), _req(G, "When CTRL.Enable")
    cov = requirement_coverage(G, {reload_id}, {G.nodes[enable_id]["chunk_id"]})
    assert cov["covered"] == 1 and enable_id in [r["req_id"] for r in cov["chunk_only"]]
    assert cov["total"] == 4 and len(cov["uncovered"]) + len(cov["chunk_only"]) == 3


def test_fetch_bundle_carries_graph_fetch(owned):
    _, _, G = owned
    b = fetch_context(G, "CTRL Enable", global_communities=1)
    assert b["schema_version"] == BUNDLE_SCHEMA_VERSION == 3
    assert {a["name"] for a in b["graph"]["anchors"]} >= {"Control Register (CTRL)", "Enable"}
    assert all("via" in r for r in b["requirements"]) and all("via" in e for e in b["evidence"])
    assert b["requirements"][0]["req_id"] == _req(G, "CTRL Enable makes")


def test_testplan_uses_ordering_and_coverage(built, monkeypatch):
    out, _, G = built
    seen = {}

    def capture(payload):
        seen[payload["section"]["id"]] = payload
        return entries_handler(payload)
    run_testplan_doc(out, _llm(testplan_entries=capture))
    assert seen["stimulus"]["dependency_order"]["order"]
    reload_id, enable_id = _req(G, "On reaching zero"), _req(G, "When CTRL.Enable")
    order = [o["req_id"] for o in seen["stimulus"]["dependency_order"]["order"]]
    assert order.index(enable_id) < order.index(reload_id)
    targets = [r["req_id"] for r in seen["checks"]["uncovered_requirements"]]
    assert targets
    doc = json.loads((out / "testplan_doc.json").read_text())
    checks = next(s for s in doc["sections"] if s["id"] == "checks")
    assert any("is not cited by any entry" in p for p in checks["repair"]["refusals"][0]["problems"])
    assert doc["coverage"]["total"] == 4
    assert "## Requirement coverage" in (out / "testplan_doc.md").read_text()


def test_coverage_repair_closes_the_gap(built):
    out, _, G = built

    def cite_targets(payload):
        data = entries_handler(payload)
        if payload["section"]["id"] == "checks" and "refusal" in payload:
            chunk = payload["chunks"][0]["chunk_id"]
            data["entries"] = [{"text": f"check for {r['req_id']}", "kind": "agent_scoreboard",
                                "provenance": "INFERRED", "cited_req_ids": [r["req_id"]], "cited_chunk_ids": [chunk],
                                "details": []} for r in payload["uncovered_requirements"]]
        return data
    summary = run_testplan_doc(out, _llm(testplan_entries=cite_targets))
    doc = json.loads((out / "testplan_doc.json").read_text())
    checks = next(s for s in doc["sections"] if s["id"] == "checks")
    assert checks["repair"]["unresolved"] == []
    assert summary["coverage"]["ratio"] == 1.0 and doc["coverage"]["uncovered"] == []


def test_cli_deps_and_global_context(built, capsys):
    out, _, G = built
    reload_id = _req(G, "On reaching zero")
    assert main(["deps", reload_id, "--out", str(out)]) == 0
    res = json.loads(capsys.readouterr().out)
    assert [o["req_id"] for o in res["order"]][-1] == reload_id and res["closure"]
    assert main(["deps", "REQ-missing", "--out", str(out)]) == 2
    capsys.readouterr()
    assert main(["context", "counter reload", "--out", str(out), "--global", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["graph"]["global_communities"]
