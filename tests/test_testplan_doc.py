import json

import pytest

from conftest import dependency_handler, extraction_handler, interfaces_handler, plan_handler, rerank_handler
from dv_agent.cli import main
from dv_agent.graph import lineage, load_graph
from dv_agent.llm import FakeLLM, LLMError
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_testplan_doc
from dv_agent.testplan_doc import load_template
from dv_agent.trace import read_trace

HEADINGS = ["1. Title", "2. Feature Description", "3. Register Map", "4. Observations from RTL", "5. High Level Verification Strategy",
            "6. Configurations", "7. Stimulus", "8. Checks", "9. Coverage", "10. Callouts to Higher Testbenches",
            "11. Assumptions", "12. Questions to Designers"]


def entries_handler(payload):
    sec = payload["section"]["id"]
    reqs = [r["req_id"] for r in payload["requirements"]]
    chunks = [c["chunk_id"] for c in payload["chunks"]]
    kind = {"feature_description": "purpose", "strategy": "uvm_agent", "stimulus": "directed_test",
            "checks": "agent_scoreboard", "coverage": "covergroup", "callouts": "reuse",
            "assumptions": "assumption", "questions": "question"}[sec]
    entries = [
        {"text": f"{sec} entry backed by evidence", "kind": kind, "provenance": "INFERRED",
         "inference_reason": "The cited behavior motivates this proposed verification action.",
         "cited_req_ids": reqs[:1], "cited_chunk_ids": chunks[:1], "details": ["detail a", " "]},
        {"text": f"{sec} unsupported claim", "kind": kind, "provenance": "DOCUMENTED",
         "cited_req_ids": [], "cited_chunk_ids": [], "details": []},
        {"text": f"{sec} bogus citation", "kind": kind, "provenance": "INFERRED",
         "cited_req_ids": ["REQ-made-up"], "cited_chunk_ids": [], "details": []},
    ]
    if sec == "stimulus":
        items = [i for p in payload["previous_sections"] for i in p["items"]]
        entries[0]["details"].append(f"strategy agents seen: {sum(i.startswith('agent ') for i in items)}")
    return {"entries": entries}


def strategy_handler(payload):
    seq = lambda n: {"name": n, "purpose": f"{n} purpose"}
    check = lambda m, d: {"mechanism": m, "description": d}
    return {"environment": "Block-level UVM environment.",
            "agents": [
                {"name": "bus_agent", "interface_groups": ["Register bus"], "mode": "active", "role": "bus master",
                 "drives": ["BUS_ADDR", "BUS_WDATA", "BUS_WE", "BUS_RDATA"], "monitors": ["BUS_RDATA", "IRQ"],
                 "registers": ["CTRL"], "sequences": [seq("reg_write")],
                 "correctness": [check("agent_scoreboard", "read data matches the register model")],
                 "cited_chunk_ids": []},
                {"name": "irq_agent", "interface_groups": ["Interrupt"], "mode": "passive", "role": "IRQ monitor",
                 "drives": ["IRQ"], "monitors": ["IRQ"], "registers": [], "sequences": [], "correctness": [],
                 "cited_chunk_ids": []},
                {"name": "clk_rst_agent", "interface_groups": ["Clock", "Reset", "Register bus"], "mode": "active",
                 "role": "clock and reset", "drives": ["CLK", "RST_N"], "monitors": [], "registers": [],
                 "sequences": [seq("reset")], "correctness": [check("protocol_assertion", "reset is held 2 cycles")],
                 "cited_chunk_ids": []}],
            "scoreboards": [
                {"name": "sb_top", "level": "top", "inputs": ["bus_agent", "irq_agent", "ghost_agent"],
                 "reference_model": "timer model", "compares": "IRQ timing vs programmed RELOAD", "registers": ["CTRL"],
                 "cited_chunk_ids": []}],
            "register_model": {"used": True, "registers": ["CTRL"], "description": "mirror checks on read"},
            "virtual_sequences": [{"name": "vseq_reset_config", "purpose": "reset then configure",
                                   "agents": ["clk_rst_agent", "bus_agent", "nobody"]}]}


def registers_handler(payload):
    regs = []
    for c in payload["chunks"]:
        if "Control Register" in c["text"]:
            regs.append({"name": "Control Register", "abbreviation": "CTRL", "address": "", "width": "8",
                         "access": "", "reset_value": "00h", "description": "Enable and interrupt enable.",
                         "availability": "", "quote": "2.1 Control Register (CTRL)", "chunk_id": c["chunk_id"],
                         "fields": [
                             {"bits": "0", "name": "Enable", "access": "RW", "reset_value": "", "description":
                              "Counter decrements when 1.", "values": [{"value": "1", "meaning": "counting"}],
                              "quote": "0 RW Enable."},
                             {"bits": "1", "name": "Interrupt enable", "access": "RW", "reset_value": "",
                              "description": "IRQ on zero.", "values": [], "quote": "1 RW Interrupt enable."}]})
            regs.append({"name": "Ghost Register", "abbreviation": "GHOST", "address": "0x40", "width": "8",
                         "access": "RO", "reset_value": "FFh", "description": "", "availability": "",
                         "quote": "", "chunk_id": c["chunk_id"], "fields": []})
    return {"registers": regs}


def configurations_handler(payload):
    fields = payload["configurable_fields"]
    first = fields[0]["field_id"]
    return {"configurations": [
        {"field_id": first, "randomize": True, "legal_values": ["0", "1"], "distribution": "uniform",
         "constraints": [], "reserved_handling": "", "notes": "", "provenance": "DOCUMENTED",
         "cited_req_ids": [], "cited_chunk_ids": []},
        {"field_id": first, "randomize": False, "legal_values": [], "distribution": "", "constraints": [],
         "reserved_handling": "", "notes": "duplicate", "provenance": "ASSUMED", "cited_req_ids": [],
         "cited_chunk_ids": []}]}


def claims_handler(payload):
    return {"judgements": [{"id": c["id"], "supported": True, "reason": ""} for c in payload["claims"]]}


def _llm(**overrides):
    handlers = {"spec_requirements": extraction_handler, "requirement_dependencies": dependency_handler,
                "rerank_chunks": rerank_handler, "test_plan_items": plan_handler,
                "testplan_entries": entries_handler, "testplan_registers": registers_handler,
                "testplan_configurations": configurations_handler, "testplan_interfaces": interfaces_handler,
                "testplan_strategy": strategy_handler, "claims_check": claims_handler}
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
    assert [s["status"] for s in summary["sections"]] == ["PASS"] * 3 + ["NOT_RUN"] + ["PASS"] * 8
    md = (run / "testplan_doc.md").read_text()
    positions = [md.index(h if h == "1. Title" else f"## {h}") if h != "1. Title" else 0 for h in HEADINGS]
    assert positions == sorted(positions)
    assert md.startswith("# Verification Test Plan: tmr32_spec")
    assert "⚠️<!--dv-evidence:" in md and "(directed_test) stimulus entry backed by evidence — sources:" in md
    assert "Inference: The cited behavior motivates this proposed verification action." in md
    doc = _doc(run)
    entry = next(s for s in doc["sections"] if s["id"] == "stimulus")["entries"][0]
    assert entry["inference_reason"] == "The cited behavior motivates this proposed verification action."
    assert "## Reference evidence" in md and "Source: doc/tmr32_spec.txt" in md
    report = (run / "testplan_doc.html").read_text()
    assert 'class="evidence-tooltip"' in report and 'href="#reference-' in report
    assert "| bus_agent | Register bus | active |" in md


def test_document_emits_named_substeps(run):
    from dv_agent.progress import set_event_sink
    events = []
    set_event_sink(events.append)
    try:
        run_testplan_doc(run, _llm())
    finally:
        set_event_sink(None)
    names = [e["id"] for e in events if e["kind"] == "substep_start"]
    assert names[:2] == ["interfaces", "registers"]
    assert "register_map" in names and "rtl_observations" in names and "coverage" in names
    assert names[-1] == "render_views"
    assert any(e["kind"] == "substep_done" and e["id"] == "render_views" and e["status"] == "PASS"
               for e in events)
    events.clear()
    set_event_sink(events.append)
    try:
        reused = run_testplan_doc(run, _llm())
    finally:
        set_event_sink(None)
    assert reused["reused"] is True
    assert any(e["kind"] == "substeps_reused" for e in events)
    assert any(e["kind"] == "substep_done" and e["id"] == "render_views" for e in events)


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


def test_register_map_section_is_rendered_from_the_register_step(run):
    llm = _llm()
    run_testplan_doc(run, llm)
    assert not any(name == "testplan_register_map" for name, _ in llm.calls)
    doc = _doc(run)
    assert [r["abbreviation"] for r in doc["registers"]["registers"]] == ["CTRL"]
    md = (run / "testplan_doc.md").read_text()
    assert "## 3. Register Map" in md and "### Control Register (CTRL) ✅<!--dv-evidence:" in md
    assert "| 0 | Enable | RW |" in md


def test_configurations_cover_every_writable_field(run):
    run_testplan_doc(run, _llm())
    doc = _doc(run)
    conf = next(s for s in doc["sections"] if s["id"] == "configurations")
    by_field = {e["field"]: e for e in conf["configurations"]}
    assert set(by_field) == {"Enable", "Interrupt enable"}
    enable = by_field["Enable"]
    assert enable["randomize"] is True and enable["legal_values"] == ["0", "1"]
    assert enable["cited_chunk_ids"] and enable["provenance"] == "DOCUMENTED"
    missing = by_field["Interrupt enable"]
    assert missing["provenance"] == "ASSUMED" and missing["randomize"] is None
    assert any("duplicate" in v for v in conf["validation"])
    questions = next(s for s in doc["sections"] if s["id"] == "questions")["entries"]
    assert any("CTRL.Interrupt enable" in q["text"] for q in questions)
    md = (run / "testplan_doc.md").read_text()
    assert md.index("## 5. High Level Verification Strategy") < md.index("## 6. Configurations") < md.index("## 7. Stimulus")


def test_later_sections_see_earlier_ones_and_assumptions_are_collected(run):
    run_testplan_doc(run, _llm())
    secs = {s["id"]: s for s in _doc(run)["sections"]}
    assert "strategy agents seen: 3" in secs["stimulus"]["entries"][0]["details"]
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
    checks = next(s for s in _doc(run)["sections"] if s["id"] == "checks")
    node = G.nodes[checks["artifact_id"]]
    assert node["type"] == "test_plan_section" and node["metadata"]["section"] == "checks"
    assert lineage(G, checks["artifact_id"])["facts"]
    spans = {r["name"]: r for r in read_trace(run / "trace.jsonl", summary["trace_id"])}
    assert spans["testplan_section:checks"]["metadata"]["fact_ids"] == checks["lineage_fact_ids"]
    strategy = next(s for s in _doc(run)["sections"] if s["id"] == "strategy")
    assert lineage(G, strategy["artifact_id"])["sources"]


def test_reuse_force_and_no_artifact_accumulation(run):
    assert run_testplan_doc(run, _llm())["reused"] is False
    llm = _llm()
    assert run_testplan_doc(run, llm)["reused"] is True and llm.calls == []
    assert run_testplan_doc(run, _llm(), scope="interrupts")["reused"] is False
    run_testplan_doc(run, _llm(), scope="interrupts", force=True)
    G = load_graph(run / GRAPH_FILE)
    tps = [n for n, d in G.nodes(data=True) if d.get("type") == "test_plan_section"]
    assert len(tps) == 20  # 10 generated sections x 2 scopes, no duplicates from the forced rerun


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
    assert out["scope"] == "timer" and len(out["sections"]) == 12


def test_pipeline_testplan_flag(spec_repo, tmp_path, capsys, monkeypatch):
    from dv_agent import cli
    monkeypatch.setattr(cli, "_llm", _llm)
    out = tmp_path / "demo"
    assert main(["pipeline", str(spec_repo), "--out", str(out), "--fresh", "--testplan"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["testplan"]["reused"] is False and (out / "testplan_doc.md").exists()


def test_coverage_observation_entries_render_as_subsection():
    from dv_agent.testplan_doc import render_markdown

    def entry(text, obs):
        return {"text": text, "kind": "covergroup", "provenance": "INFERRED",
                "cited_req_ids": [], "cited_chunk_ids": [],
                "cited_rtl_observation_ids": obs, "details": [], "validation": []}

    doc = {"sections": [
        {"id": "coverage", "heading": "9. Coverage", "generator": "entries", "status": "PASS",
         "entries": [entry("observation-driven cover", ["RTLOBS-1"]),
                     entry("plain scenario cover", [])]}],
           "coverage": None, "token_usage": None}
    md = render_markdown(doc)
    head = md.index("### Coverage from RTL observations")
    assert md.index("plain scenario cover") < head < md.index("observation-driven cover")
    assert "NEEDS_REVIEW: RTL design engineer approval required." in md


def test_checks_and_coverage_render_as_tables_with_trailing_status():
    from dv_agent.testplan_doc import render_markdown

    def entry(text, kind="assertion", obs=(), status="NOT_RUN"):
        return {"text": text, "kind": kind, "provenance": "INFERRED",
                "cited_req_ids": ["REQ-1"], "cited_chunk_ids": ["CH-1"],
                "cited_rtl_observation_ids": list(obs), "details": ["detail a"],
                "validation": [], "status": status}

    plain = entry("plain cover", "covergroup")
    obs_entry = entry("obs cover", "cover_property", obs=["RTLOBS-1"])
    check_sec = {"id": "checks", "heading": "8. Checks", "generator": "entries",
                 "status": "PASS",
                 "entries": [entry("ack follows req", "assertion")]}
    cov_sec = {"id": "coverage", "heading": "9. Coverage", "generator": "entries",
               "status": "PASS", "entries": [plain, obs_entry]}
    doc = {"sections": [check_sec, cov_sec],
           "coverage": None, "token_usage": None}
    md = render_markdown(doc)
    assert md.count("| # | Description | Kind | Details | Sources | Provenance | Status |") == 3
    assert "| 1 | ack follows req | assertion | detail a<br/>Inference: Reason not supplied; designer review required. | REQ-1, CH-1 | ⚠️<!--dv-evidence:" in md
    assert "| NOT_RUN |" in md
    head = md.index("### Coverage from RTL observations")
    obs_row = md.index("| 2 | obs cover | cover_property |")
    assert head < obs_row
    assert obs_row < md.index("| NOT_RUN |", obs_row) < md.index("\n", obs_row)


def test_html_is_rendered_from_the_exact_markdown_and_recovered_without_model_calls(run, monkeypatch, capsys):
    from dv_agent.html_report import render_html
    llm = _llm()
    result = run_testplan_doc(run, llm)
    md = (run / "testplan_doc.md").read_text()
    assert (run / "testplan_doc.html").read_text() == render_html(md)
    assert result["html"] == str(run / "testplan_doc.html")
    (run / "testplan_doc.html").unlink()
    edited = md + "\n## Engineer edits\n\nReviewed control settings.\n"
    (run / "testplan_doc.md").write_text(edited)
    def fail():
        raise AssertionError("rendering must not call a model")
    monkeypatch.setattr("dv_agent.cli._llm", fail)
    assert main(["render-testplan", "--out", str(run)]) == 0
    assert json.loads(capsys.readouterr().out)["html"] == result["html"]
    assert (run / "testplan_doc.html").read_text() == render_html(edited)
    assert (run / "testplan_doc.md").read_text() == edited
    cached_llm = _llm()
    assert run_testplan_doc(run, cached_llm)["reused"] is True
    assert cached_llm.calls == []
    assert (run / "testplan_doc.md").read_text() == edited


def test_configurations_are_blocked_when_register_extraction_failed(run):
    def fail(payload):
        raise LLMError("incomplete", "limited")
    run_testplan_doc(run, _llm(testplan_registers=fail))
    doc = _doc(run)
    assert doc["registers"]["status"] == "BLOCKED"
    section = next(s for s in doc["sections"] if s["id"] == "configurations")
    assert section["status"] == "BLOCKED"


def test_old_register_extraction_invalidates_dependent_testplan_cache(run):
    run_testplan_doc(run, _llm())
    doc = _doc(run)
    doc["registers"].pop("extraction_signature")
    (run / "testplan_doc.json").write_text(json.dumps(doc))
    assert run_testplan_doc(run, _llm())["reused"] is False


def test_llm_configuration_identification_feeds_strategy_and_configuration_sections(run):
    seen = set()
    def identified(payload):
        result = registers_handler(payload)
        for r in result["registers"]:
            if r["abbreviation"] != "CTRL":
                continue
            r |= dict(configurable=True, configuration_reason="Select counter operating enables",
                      configuration_quote=r["quote"])
            for f in r["fields"]:
                f |= dict(configurable=True, configuration_reason="Enable control", configuration_quote=f["quote"])
        return result
    def strategy(payload):
        ctrl = next(r for r in payload["registers"] if r["register"] == "CTRL")
        assert ctrl["configuration"]["configurable"] is True
        assert all(c["identification"] == "LLM" for c in ctrl["configuration_controls"])
        seen.add("strategy")
        return strategy_handler(payload)
    def configurations(payload):
        assert all(f["identification"] == "LLM" for f in payload["configurable_fields"])
        assert all(f["configuration_reason"] == "Enable control" for f in payload["configurable_fields"])
        seen.add("configurations")
        return configurations_handler(payload)
    run_testplan_doc(run, _llm(testplan_registers=identified, testplan_strategy=strategy,
                               testplan_configurations=configurations))
    assert seen == {"strategy", "configurations"}
