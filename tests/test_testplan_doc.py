import json

import pytest

from conftest import dependency_handler, extraction_handler, interfaces_handler, plan_handler, rerank_handler
from dv_agent.cli import main
from dv_agent.graph import lineage, load_graph
from dv_agent.llm import FakeLLM, LLMError
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_testplan_doc
from dv_agent.testplan_doc import load_template
from dv_agent.trace import read_trace

HEADINGS = ["1. Title", "2. Feature Description", "3. Register Map", "4. High Level Verification Strategy",
            "5. Stimulus", "6. Checks", "7. Coverage", "8. Callouts to Higher Testbenches",
            "9. Assumptions", "10. Questions to Designers"]


def entries_handler(payload):
    sec = payload["section"]["id"]
    reqs = [r["req_id"] for r in payload["requirements"]]
    chunks = [c["chunk_id"] for c in payload["chunks"]]
    kind = {"feature_description": "purpose", "strategy": "uvm_agent", "stimulus": "directed_test",
            "checks": "agent_scoreboard", "coverage": "covergroup", "callouts": "reuse",
            "assumptions": "assumption", "questions": "question"}[sec]
    entries = [
        {"text": f"{sec} entry backed by evidence", "kind": kind, "provenance": "INFERRED",
         "cited_req_ids": reqs[:1], "cited_chunk_ids": chunks[:1], "details": ["detail a", " "]},
        {"text": f"{sec} unsupported claim", "kind": kind, "provenance": "DOCUMENTED",
         "cited_req_ids": [], "cited_chunk_ids": [], "details": []},
        {"text": f"{sec} bogus citation", "kind": kind, "provenance": "INFERRED",
         "cited_req_ids": ["REQ-made-up"], "cited_chunk_ids": [], "details": []},
    ]
    if sec == "strategy":
        entries[0]["details"].append(f"previous sections seen: {len(payload['previous_sections'])}")
    return {"entries": entries}


def register_handler(payload):
    ctrl = next(c["chunk_id"] for c in payload["chunks"] if "Control Register" in c["text"])
    return {"registers": [
        {"name": "Control Register", "abbreviation": "CTRL", "address": "", "width": "", "access": "RW",
         "reset_value": "00h", "description": "Enable and interrupt enable bits.", "provenance": "DOCUMENTED",
         "cited_req_ids": [], "cited_chunk_ids": [ctrl],
         "fields": [{"bits": "0", "name": "Enable", "access": "RW", "reset_value": "",
                     "description": "Counter decrements when 1."}]},
        {"name": "Ghost Register", "abbreviation": "GHOST", "address": "0x40", "width": "8", "access": "RO",
         "reset_value": "FFh", "description": "Not in the spec.", "provenance": "DOCUMENTED",
         "cited_req_ids": [], "cited_chunk_ids": [ctrl], "fields": []}]}


def _llm(**overrides):
    handlers = {"spec_requirements": extraction_handler, "requirement_dependencies": dependency_handler,
                "rerank_chunks": rerank_handler, "test_plan_items": plan_handler,
                "testplan_entries": entries_handler, "testplan_register_map": register_handler,
                "testplan_interfaces": interfaces_handler}
    handlers.update(overrides)
    return FakeLLM(handlers)


@pytest.fixture
def run(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm())
    return out


def _doc(out):
    return json.loads((out / "testplan_doc.json").read_text())


def test_template_loads_and_validates(tmp_path):
    t = load_template()
    assert [s["heading"] for s in t["sections"]] == HEADINGS
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"template_id": "x", "sections": [{"id": "a", "heading": "A", "generator": "nope"}]}))
    with pytest.raises(ValueError):
        load_template(bad)


def test_document_has_all_sections_in_template_order(run):
    summary = run_testplan_doc(run, _llm())
    assert [s["status"] for s in summary["sections"]] == ["PASS"] * 10
    md = (run / "testplan_doc.md").read_text()
    positions = [md.index(h if h == "1. Title" else f"## {h}") if h != "1. Title" else 0 for h in HEADINGS]
    assert positions == sorted(positions)
    assert md.startswith("# Verification Test Plan: tmr32_spec")
    assert "[INFERRED] (uvm_agent) strategy entry backed by evidence — sources:" in md


def test_citations_are_enforced_and_provenance_downgraded(run):
    run_testplan_doc(run, _llm())
    checks = next(s for s in _doc(run)["sections"] if s["id"] == "checks")
    by_text = {e["text"]: e for e in checks["entries"]}
    assert by_text["checks entry backed by evidence"]["provenance"] == "INFERRED"
    assert by_text["checks entry backed by evidence"]["details"] == ["detail a"]
    unsupported = by_text["checks unsupported claim"]
    assert unsupported["provenance"] == "ASSUMED" and "downgraded" in unsupported["validation"][0]
    bogus = by_text["checks bogus citation"]
    assert bogus["cited_req_ids"] == [] and bogus["provenance"] == "ASSUMED"


def test_register_values_checked_against_cited_text(run):
    run_testplan_doc(run, _llm())
    regs = {r["abbreviation"]: r for r in next(s for s in _doc(run)["sections"] if s["id"] == "register_map")["registers"]}
    assert regs["CTRL"]["provenance"] == "DOCUMENTED" and regs["CTRL"]["validation"] == []
    assert regs["GHOST"]["provenance"] == "INFERRED"
    assert "address, reset_value not found verbatim" in regs["GHOST"]["validation"][0]


def test_later_sections_see_earlier_ones_and_assumptions_are_collected(run):
    run_testplan_doc(run, _llm())
    secs = {s["id"]: s for s in _doc(run)["sections"]}
    assert "previous sections seen: 2" in secs["strategy"]["entries"][0]["details"]
    collected = [e for e in secs["assumptions"]["entries"] if e["details"][:1] and e["details"][0].startswith("Collected from")]
    assert any(e["text"] == "checks unsupported claim" for e in collected)
    assert len({e["text"] for e in secs["assumptions"]["entries"]}) == len(secs["assumptions"]["entries"])


def test_conflicts_become_designer_questions(spec_repo, tmp_path):
    def conflicting(payload):
        data = dependency_handler(payload)
        for e in data["edges"]:
            if e["type"] == "DEPENDS_ON":
                e["type"] = "CONFLICTS_WITH"
        return data
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(requirement_dependencies=conflicting))
    run_testplan_doc(out, _llm(), scope="counter reload")
    questions = next(s for s in _doc(out)["sections"] if s["id"] == "questions")["entries"]
    assert any(e["text"].startswith("The specification appears contradictory") and len(e["cited_req_ids"]) == 2
               for e in questions)


def test_sections_recorded_with_lineage_and_trace(run):
    summary = run_testplan_doc(run, _llm())
    G = load_graph(run / GRAPH_FILE)
    strategy = next(s for s in _doc(run)["sections"] if s["id"] == "strategy")
    node = G.nodes[strategy["artifact_id"]]
    assert node["type"] == "test_plan_section" and node["metadata"]["section"] == "strategy"
    assert lineage(G, strategy["artifact_id"])["facts"]
    spans = {r["name"]: r for r in read_trace(run / "trace.jsonl", summary["trace_id"])}
    assert spans["testplan_section:strategy"]["metadata"]["fact_ids"] == strategy["lineage_fact_ids"]


def test_reuse_force_and_no_artifact_accumulation(run):
    assert run_testplan_doc(run, _llm())["reused"] is False
    llm = _llm()
    assert run_testplan_doc(run, llm)["reused"] is True and llm.calls == []
    assert run_testplan_doc(run, _llm(), scope="interrupts")["reused"] is False
    run_testplan_doc(run, _llm(), scope="interrupts", force=True)
    G = load_graph(run / GRAPH_FILE)
    tps = [n for n, d in G.nodes(data=True) if d.get("type") == "test_plan_section"]
    assert len(tps) == 18  # 9 generated sections x 2 scopes, no duplicates from the forced rerun


def test_blocked_section_is_reported_and_not_reused(run):
    def failing(payload):
        if payload["section"]["id"] == "coverage":
            raise LLMError("transient", "simulated")
        return entries_handler(payload)
    summary = run_testplan_doc(run, _llm(testplan_entries=failing))
    status = {s["id"]: s["status"] for s in summary["sections"]}
    assert status["coverage"] == "BLOCKED" and status["checks"] == "PASS"
    assert "**BLOCKED**" in (run / "testplan_doc.md").read_text()
    assert run_testplan_doc(run, _llm())["reused"] is False


def test_cli_testplan(run, capsys, monkeypatch):
    from dv_agent import cli
    monkeypatch.setattr(cli, "_llm", lambda: None)
    assert main(["testplan", "--out", str(run)]) == 2
    monkeypatch.setattr(cli, "_llm", _llm)
    capsys.readouterr()
    assert main(["testplan", "--out", str(run), "--scope", "timer"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["scope"] == "timer" and len(out["sections"]) == 10


def test_pipeline_testplan_flag(spec_repo, tmp_path, capsys, monkeypatch):
    from dv_agent import cli
    monkeypatch.setattr(cli, "_llm", _llm)
    out = tmp_path / "demo"
    assert main(["pipeline", str(spec_repo), "--out", str(out), "--fresh", "--testplan"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["testplan"]["reused"] is False and (out / "testplan_doc.md").exists()
