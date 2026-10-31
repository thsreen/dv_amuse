import json

import pytest

from conftest import dependency_handler, extraction_handler, interfaces_handler, plan_handler, rerank_handler
from dv_agent.cli import main
from dv_agent.graph.graph import lineage, load_graph
from dv_agent.core.llm import FakeLLM, LLMError
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_testplan_doc
from dv_agent.plan.testplan_doc import load_template
from dv_agent.core.trace import read_trace

HEADINGS = ["1. Document Overview", "2. Feature Description", "3. Register Map", "4. Observations from RTL", "5. High Level Verification Strategy",
            "6. Verification Plan", "7. Configurations", "8. Sequences and Stimulus", "9. Checks and Scoreboards", "10. Functional Coverage", "11. Integration and Reuse",
            "12. Assumptions", "13. Questions to Designers"]


def entries_handler(payload):
    sec = payload["section"]["id"]
    reqs = [r["req_id"] for r in payload["requirements"]]
    chunks = [c["chunk_id"] for c in payload["chunks"]]
    kind = {"feature_description": "purpose", "strategy": "uvm_agent", "verification_plan": "sequence_implementation", "stimulus": "directed_test",
            "checks": "agent_scoreboard", "coverage": "covergroup", "callouts": "reuse",
            "assumptions": "assumption", "questions": "question"}[sec]
    if sec == "feature_description":
        source = payload["chunks"][0]
        return {"entries": [dict(text=source["text"], kind=kind, provenance="DOCUMENTED", inference_reason="",
                                 cited_req_ids=[], cited_chunk_ids=[source["chunk_id"]], details=[])]}
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
    run_build_graph(out, _llm(), mode="graph")
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
    summary = run_testplan_doc(run, _llm(), mode="graph")
    assert [s["status"] for s in summary["sections"]] == ["PASS"] * 3 + ["NOT_RUN"] + ["PASS"] * 9
    md = (run / "testplan_doc.md").read_text()
    positions = [0 if h == HEADINGS[0] else md.index(f"## {h}") for h in HEADINGS]
    assert positions == sorted(positions)
    assert md.startswith("# Verification Test Plan: tmr32_spec")
    # Stimulus: the indicator comes last and carries the sources instead of trailing "sources:" text.
    assert "stimulus entry backed by evidence ⚠️<!--dv-evidence:" in md and "stimulus entry backed by evidence — sources:" not in md
    assert "### Directed Test" in md and "(directed_test)" not in md
    assert "Inference: The cited behavior motivates this proposed verification action." in md
    doc = _doc(run)
    entry = next(s for s in doc["sections"] if s["id"] == "stimulus")["entries"][0]
    assert entry["inference_reason"] == "The cited behavior motivates this proposed verification action."
    assert "## Reference evidence" in md and "Source: doc/tmr32_spec.txt" in md
    report = (run / "testplan_doc.html").read_text()
    assert 'class="evidence-tooltip"' in report and 'href="#reference-' in report
    assert "Agent `bus_agent` (active)" in md


def test_feature_description_has_one_documented_heading_and_subtle_note(run):
    run_testplan_doc(run, _llm(), mode="graph")
    md = (run / "testplan_doc.md").read_text()
    section = md.split("## 2. Feature Description", 1)[1].split("## 3. Register Map", 1)[0]
    assert section.count("✅<!--dv-evidence:") == 1
    assert "_Provenance: documented specification facts only;" in section
    assert "⚠️<!--dv-evidence:" not in section and "🛑<!--dv-evidence:" not in section
    assert 'class="provenance-note"' in (run / "testplan_doc.html").read_text()


def test_saved_json_controls_subsection_titles_and_entry_grouping(run):
    from dv_agent.plan.testplan_doc import render_markdown
    run_testplan_doc(run, _llm(), mode="graph")
    doc = _doc(run)
    assert doc["presentation"]["subsection_heading_level"] == 3
    assert doc["presentation"]["subsection_emphasis"] == "bold"
    for section in doc["sections"]:
        if section["generator"] == "entries":
            indexes = [i for sub in section["subsections"] for i in sub["entry_indexes"]]
            assert sorted(indexes) == list(range(len(section["entries"])))
            assert len(indexes) == len(set(indexes))
    plan = next(s for s in doc["sections"] if s["id"] == "verification_plan")
    assert plan["subsections"][0]["heading"] == "Sequence Implementation"
    assert plan["subsections"][0]["layout"] == "bullets"
    plan["subsections"][0]["heading"] = "Reviewed Sequence Implementation"
    md = render_markdown(json.loads(json.dumps(doc)))
    assert "### Reviewed Sequence Implementation" in md
    register = next(s for s in doc["sections"] if s["id"] == "register_map")["subsections"][0]
    assert register["layout"] == "expandable_row"
    assert [sub["heading"] for sub in register["detail_subsections"]] == ["Description", "Fields"]


def test_feature_description_never_promotes_an_inferred_claim(run):
    from dv_agent.plan.testplan_doc import DocConfig
    def inferred(payload):
        result = entries_handler(payload)
        if payload["section"]["id"] == "feature_description":
            result["entries"][0]["provenance"] = "INFERRED"
        return result
    run_testplan_doc(run, _llm(testplan_entries=inferred), cfg=DocConfig(max_repairs=0), mode="graph")
    section = next(s for s in _doc(run)["sections"] if s["id"] == "feature_description")
    assert section["status"] == "BLOCKED" and section["entries"] == []


def test_document_emits_named_substeps(run):
    from dv_agent.core.progress import set_event_sink
    events = []
    set_event_sink(events.append)
    try:
        run_testplan_doc(run, _llm(), mode="graph")
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
        reused = run_testplan_doc(run, _llm(), mode="graph")
    finally:
        set_event_sink(None)
    assert reused["reused"] is True
    assert any(e["kind"] == "substeps_reused" for e in events)
    assert any(e["kind"] == "substep_done" and e["id"] == "render_views" for e in events)


def test_citations_are_enforced_and_provenance_downgraded(run):
    run_testplan_doc(run, _llm(), mode="graph")
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
    run_testplan_doc(run, llm, mode="graph")
    assert not any(name == "testplan_register_map" for name, _ in llm.calls)
    doc = _doc(run)
    assert [r["abbreviation"] for r in doc["registers"]["registers"]] == ["CTRL"]
    md = (run / "testplan_doc.md").read_text()
    assert "## 3. Register Map ✅<!--dv-evidence:" in md and "### Control Register (CTRL)" in md
    assert "| 0 | Enable | RW |" in md


def test_configurations_cover_every_writable_field(run):
    run_testplan_doc(run, _llm(), mode="graph")
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
    assert md.index("## 5. High Level Verification Strategy") < md.index("## 6. Verification Plan") < md.index("## 7. Configurations") < md.index("## 8. Sequences and Stimulus")


def test_later_sections_see_earlier_ones_and_assumptions_are_collected(run):
    run_testplan_doc(run, _llm(), mode="graph")
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
    run_build_graph(out, _llm(requirement_dependencies=conflicting), mode="graph")
    run_testplan_doc(out, _llm(), scope="counter reload", mode="graph")
    questions = next(s for s in _doc(out)["sections"] if s["id"] == "questions")["entries"]
    assert any(e["text"].startswith("The specification appears contradictory") and len(e["cited_req_ids"]) == 2
               for e in questions)


def test_sections_recorded_with_lineage_and_trace(run):
    summary = run_testplan_doc(run, _llm(), mode="graph")
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
    assert run_testplan_doc(run, _llm(), mode="graph")["reused"] is False
    llm = _llm()
    assert run_testplan_doc(run, llm, mode="graph")["reused"] is True and llm.calls == []
    assert run_testplan_doc(run, _llm(), scope="interrupts", mode="graph")["reused"] is False
    run_testplan_doc(run, _llm(), scope="interrupts", force=True, mode="graph")
    G = load_graph(run / GRAPH_FILE)
    tps = [n for n, d in G.nodes(data=True) if d.get("type") == "test_plan_section"]
    assert len(tps) == 22  # 11 generated sections x 2 scopes, no duplicates from the forced rerun


def test_blocked_section_is_reported_and_not_reused(run):
    def failing(payload):
        if payload["section"]["id"] == "coverage":
            raise LLMError("transient", "simulated")
        return entries_handler(payload)
    summary = run_testplan_doc(run, _llm(testplan_entries=failing), mode="graph")
    status = {s["id"]: s["status"] for s in summary["sections"]}
    assert status["coverage"] == "BLOCKED" and status["checks"] == "PASS"
    assert "**BLOCKED**" in (run / "testplan_doc.md").read_text()
    assert run_testplan_doc(run, _llm(), mode="graph")["reused"] is False


def test_blocked_registers_prevent_dependent_calls_and_propagate_status(run, monkeypatch):
    from dv_agent.plan import testplan_doc
    original = testplan_doc._registers_step

    def partial(*args, **kwargs):
        result = original(*args, **kwargs)
        return result | {"status": "BLOCKED", "validation": ["Initialization extraction incomplete"]}

    monkeypatch.setattr(testplan_doc, "_registers_step", partial)
    llm = _llm()
    summary = run_testplan_doc(run, llm, mode="graph")
    doc = _doc(run)
    sections = {s["id"]: s for s in doc["sections"]}
    for name in ("verification_plan", "configurations", "stimulus", "checks", "coverage", "callouts"):
        assert sections[name]["status"] == "BLOCKED"
        assert sections[name]["blocked_by"]
        assert sections[name]["dependencies"]
    assert set(sections["configurations"]["blocked_by"]) == {"@registers", "feature_description", "register_map", "verification_plan"}
    assert {"@registers", "feature_description", "register_map"} <= set(sections["stimulus"]["blocked_by"])
    assert all(s["status"] == "BLOCKED" for s in sections.values())
    generated = [payload["section"]["id"] for name, payload in llm.calls if name == "testplan_entries"]
    assert not set(generated) & {"verification_plan", "stimulus", "checks", "coverage", "callouts"}
    assert not any(name == "testplan_configurations" for name, _ in llm.calls)
    assert not generated
    assert not any(name == "testplan_strategy" for name, _ in llm.calls)
    assert summary["status"] == doc["status"] == "BLOCKED"
    assert summary["generation_status"] == doc["generation_status"] == "PARTIAL"
    for name in ("testplan_doc.md", "testplan_doc.html"):
        rendered = (run / name).read_text()
        assert "Generation readiness:" in rendered and "Unresolved prerequisites:" in rendered
        assert "Initialization extraction incomplete" not in rendered or "BLOCKED" in rendered


def test_failed_stimulus_blocks_all_remaining_sections(run):
    def failed(payload):
        if payload["section"]["id"] == "stimulus":
            raise LLMError("transient", "stimulated failure")
        return entries_handler(payload)

    llm = _llm(testplan_entries=failed)
    summary = run_testplan_doc(run, llm, mode="graph")
    sections = {s["id"]: s for s in _doc(run)["sections"]}
    assert sections["checks"]["blocked_by"] == ["stimulus"]
    assert sections["coverage"]["blocked_by"] == ["stimulus", "checks"]
    assert sections["questions"]["status"] == "BLOCKED"
    assert summary["status"] == "BLOCKED"
    assert not any(n == "testplan_entries" and p["section"]["id"] in ("checks", "coverage") for n, p in llm.calls)


@pytest.mark.parametrize("failed_section", ["feature_description", "strategy", "verification_plan", "configurations", "stimulus", "checks", "coverage", "callouts", "assumptions"])
def test_every_section_waits_for_previous_success(run, failed_section):
    def failed(payload):
        if payload["section"]["id"] == failed_section:
            raise LLMError("transient", "simulated failure")
        return entries_handler(payload)

    def fail_step(payload):
        raise LLMError("transient", "simulated failure")

    overrides = {"testplan_entries": failed}
    if failed_section in ("strategy", "configurations"):
        overrides["testplan_" + failed_section] = fail_step
    llm = _llm(**overrides)
    summary = run_testplan_doc(run, llm, mode="graph")
    sections = _doc(run)["sections"]
    index = next(i for i, s in enumerate(sections) if s["id"] == failed_section)
    assert sections[index]["status"] == "BLOCKED"
    for previous, current in zip(sections[index:], sections[index + 1:]):
        assert current["status"] == "BLOCKED"
        assert previous["id"] in current["blocked_by"]
        assert not current.get("entries")
        assert not any(n == "testplan_entries" and p["section"]["id"] == current["id"] for n, p in llm.calls)
    assert summary["status"] == "BLOCKED" and summary["generation_status"] == "PARTIAL"


def test_custom_template_cannot_bypass_sequential_gates(run, tmp_path):
    from dv_agent.plan.testplan_doc import DEFAULT_TEMPLATE
    template = json.loads(DEFAULT_TEMPLATE.read_text())
    template.pop("execution_policy", None)
    for section in template["sections"]:
        section.pop("depends_on", None)
    path = tmp_path / "custom.json"
    path.write_text(json.dumps(template))

    def fail(payload):
        if payload["section"]["id"] == "checks":
            raise LLMError("transient", "simulated failure")
        return entries_handler(payload)

    llm = _llm(testplan_entries=fail)
    run_testplan_doc(run, llm, template_path=path, mode="graph")
    doc = _doc(run)
    sections = {s["id"]: s for s in doc["sections"]}
    assert sections["coverage"]["blocked_by"] == ["checks"]
    assert sections["questions"]["status"] == "BLOCKED"
    assert doc["execution_policy"] == "strict_sequence"
    assert not any(n == "testplan_entries" and p["section"]["id"] == "coverage" for n, p in llm.calls)


@pytest.mark.parametrize("bypass", ["disabled_registers", "missing_feature", "missing_map", "reordered_checks"])
def test_required_foundations_cannot_be_bypassed(run, tmp_path, bypass):
    from dv_agent.plan.testplan_doc import DEFAULT_TEMPLATE
    template = json.loads(DEFAULT_TEMPLATE.read_text())
    for section in template["sections"]:
        section.pop("depends_on", None)
    if bypass == "disabled_registers":
        template["registers"] = {"enabled": False}
    elif bypass in ("missing_feature", "missing_map"):
        omitted = "feature_description" if bypass == "missing_feature" else "register_map"
        template["sections"] = [s for s in template["sections"] if s["id"] != omitted]
    else:
        checks = next(s for s in template["sections"] if s["id"] == "checks")
        template["sections"].remove(checks)
        template["sections"].insert(1, checks)
    path = tmp_path / "bypass.json"
    path.write_text(json.dumps(template))
    llm = _llm()
    summary = run_testplan_doc(run, llm, template_path=path, mode="graph")
    assert summary["status"] == "BLOCKED" and summary["generation_status"] == "PARTIAL"
    assert not any(n == "testplan_entries" and p["section"]["id"] in ("checks", "stimulus", "coverage") for n, p in llm.calls)
    assert not any(n == "testplan_strategy" for n, p in llm.calls)
    blocked = {b["id"] for b in summary["blocking_dependencies"]}
    assert blocked & {"@registers", "feature_description", "register_map"}


def test_dependency_contract_and_register_context_reach_model(run):
    llm = _llm()
    summary = run_testplan_doc(run, llm, mode="graph")
    stimulus = next(p for n, p in llm.calls if n == "testplan_entries" and p["section"]["id"] == "stimulus")
    assert all(d["satisfied"] for d in stimulus["section_dependencies"])
    assert stimulus["register_context"]["registers"]
    assert stimulus["register_context"]["configurable_fields"]
    assert stimulus["configuration_context"]["status"] == "PASS"
    checks = next(p for n, p in llm.calls if n == "testplan_entries" and p["section"]["id"] == "checks")
    assert next(s for s in checks["prerequisite_sections"] if s["id"] == "stimulus")["entries"]
    assert summary["status"] == "PASS" and summary["generation_status"] == "COMPLETE"


@pytest.mark.parametrize("dependencies", [["missing"], ["a"], "a"])
def test_invalid_section_dependencies_rejected(tmp_path, dependencies):
    path = tmp_path / "dependencies.json"
    path.write_text(json.dumps({"template_id": "custom", "sections": [
        {"id": "a", "heading": "A", "generator": "entries", "depends_on": dependencies}]}))
    with pytest.raises(ValueError, match="depend"):
        load_template(path)


def test_interrupted_generation_saves_partial_json_markdown_html_and_can_resume(run):
    def interrupted(payload): raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): run_testplan_doc(run,_llm(testplan_entries=interrupted), mode="graph")
    partial=json.loads((run/'testplan_doc.json').read_text())
    assert partial['generation_status']=='INTERRUPTED' and partial['interruption_type']=='KeyboardInterrupt'
    assert partial['status'] == 'BLOCKED'
    assert partial['completed_sections']==['title']
    assert partial['sections'][0]['status']=='PASS'
    assert all(s['status']=='NOT_RUN' for s in partial['sections'][1:])
    assert 'Generation interrupted' in (run/'testplan_doc.md').read_text()
    assert 'Generation interrupted' in (run/'testplan_doc.html').read_text()
    assert partial['interfaces'] and partial['registers']
    resumed=run_testplan_doc(run,_llm(), mode="graph")
    assert resumed['reused'] is False
    complete=json.loads((run/'testplan_doc.json').read_text())
    assert complete['generation_status']=='COMPLETE'


def test_cli_testplan(run, capsys, monkeypatch):
    from dv_agent import cli
    monkeypatch.setattr(cli, "_llm", lambda: None)
    assert main(["testplan", "--out", str(run)]) == 2
    monkeypatch.setattr(cli, "_llm", _llm)
    capsys.readouterr()
    assert main(["testplan", "--out", str(run), "--scope", "timer"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["scope"] == "timer" and len(out["sections"]) == 13


def test_pipeline_testplan_flag(spec_repo, tmp_path, capsys, monkeypatch):
    from dv_agent import cli
    monkeypatch.setattr(cli, "_llm", _llm)
    out = tmp_path / "demo"
    assert main(["pipeline", str(spec_repo), "--out", str(out), "--fresh", "--testplan"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["testplan"]["reused"] is False and (out / "testplan_doc.md").exists()


@pytest.mark.parametrize("command", ["testplan", "pipeline"])
def test_cli_returns_failure_for_blocked_plan(run, spec_repo, capsys, monkeypatch, command):
    from dv_agent import cli

    def fail(payload):
        if payload["section"]["id"] == "stimulus":
            raise LLMError("transient", "simulated")
        return entries_handler(payload)

    monkeypatch.setattr(cli, "_llm", lambda: _llm(testplan_entries=fail))
    args = (["pipeline", str(spec_repo), "--testplan"] if command == "pipeline" else ["testplan"])
    assert main(args + ["--out", str(run)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "BLOCKED"


def test_coverage_observation_entries_render_as_subsection():
    from dv_agent.plan.testplan_doc import render_markdown

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


def test_checks_and_coverage_render_as_tables_with_indicators_beside_descriptions():
    from dv_agent.plan.testplan_doc import render_markdown

    def entry(text, kind="assertion", obs=(), status="NOT_RUN", **extra):
        return {"text": text, "kind": kind, "provenance": "INFERRED",
                "cited_req_ids": ["REQ-1"], "cited_chunk_ids": ["CH-1"],
                "cited_rtl_observation_ids": list(obs), "details": ["detail a"],
                "validation": [], "status": status} | extra

    plain = entry("plain cover cg_x", "covergroup", covergroup="cg_x",
                  coverpoints=[dict(name="cp_a", bins=["low", "high"]), dict(name="cp_b", bins=["on"])])
    cover = entry("cover property c_ack for a_ack", "cover_property")
    obs_entry = entry("obs cover", "covergroup", obs=["RTLOBS-1"])
    check_sec = {"id": "checks", "heading": "8. Checks", "generator": "entries",
                 "status": "PASS", "entries": [entry("ack follows req", "assertion")]}
    cov_sec = {"id": "coverage", "heading": "9. Coverage", "generator": "entries",
               "status": "PASS", "entries": [plain, cover, obs_entry]}
    md = render_markdown({"sections": [check_sec, cov_sec], "coverage": None, "token_usage": None})
    # Checks: no source or status column; the indicator follows the description.
    assert "| # | Description | Kind | Details |" in md and "NOT_RUN" not in md
    assert "| 1 | ack follows req ⚠️<!--dv-evidence:" in md
    # Coverage: assertion table and covergroup table are separate, RTL-derived coverage stays apart.
    assert md.index("### Assertion Coverage") < md.index("### Covergroups") < md.index("### Coverage from RTL observations")
    assert "| # | Description | Assertion | Cover property | Covered |" in md
    assert "| # | Description | Covergroup | Coverpoint | Coverbin | Covered |" in md
    assert "| c_ack" in md and "| a_ack" in md
    rows = [l for l in md.splitlines() if l.startswith("| 1 | plain cover") or l.startswith("|  |  | cg_x")]
    assert len(rows) == 2 and "| cg_x | cp_a | low<br/>high | NOT_COVERED |" in rows[0] and rows[1].endswith("| cg_x | cp_b | on | NOT_COVERED |")
    assert md.count("NOT_COVERED") == 4


def test_coverage_without_cover_properties_flags_every_assertion_for_review():
    from dv_agent.plan.testplan_doc import render_markdown
    e = {"text": "ack follows req", "kind": "assertion", "provenance": "DOCUMENTED", "cited_req_ids": [],
         "cited_chunk_ids": ["CH-1"], "cited_rtl_observation_ids": [], "details": [], "validation": []}
    cov = dict(e, text="cg", kind="covergroup")
    md = render_markdown({"sections": [{"id": "checks", "heading": "8", "generator": "entries", "status": "PASS", "entries": [e]},
                                       {"id": "coverage", "heading": "9", "generator": "entries", "status": "PASS", "entries": [cov]}],
                          "coverage": None, "token_usage": None})
    assert "No cover properties were generated for the 1 assertion(s)" in md and "NEEDS_REVIEW" in md


def test_html_is_rendered_from_the_exact_markdown_and_recovered_without_model_calls(run, monkeypatch, capsys):
    from dv_agent.report.html_report import render_html
    llm = _llm()
    result = run_testplan_doc(run, llm, mode="graph")
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
    assert run_testplan_doc(run, cached_llm, mode="graph")["reused"] is True
    assert cached_llm.calls == []
    assert (run / "testplan_doc.md").read_text() == edited


def test_configurations_are_blocked_when_register_extraction_failed(run):
    def fail(payload):
        raise LLMError("incomplete", "limited")
    run_testplan_doc(run, _llm(testplan_registers=fail), mode="graph")
    doc = _doc(run)
    assert doc["registers"]["status"] == "BLOCKED"
    section = next(s for s in doc["sections"] if s["id"] == "configurations")
    assert section["status"] == "BLOCKED"


def test_old_register_extraction_invalidates_dependent_testplan_cache(run):
    run_testplan_doc(run, _llm(), mode="graph")
    doc = _doc(run)
    doc["registers"].pop("extraction_signature")
    (run / "testplan_doc.json").write_text(json.dumps(doc))
    assert run_testplan_doc(run, _llm(), mode="graph")["reused"] is False


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
                               testplan_configurations=configurations), mode="graph")
    assert seen == {"strategy", "configurations"}


def test_section_context_slim_returns_chunk_only_context(spec_repo, tmp_path):
    from dv_agent.graph.graph import build_structure
    from dv_agent.ingest.ingest import load_chunks, load_manifest
    from dv_agent.retrieval.retrieval import layered_view
    from dv_agent.retrieval.slim_index import build_index
    from dv_agent.plan.testplan_doc import DocConfig, section_context

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    G = build_structure(load_manifest(out), load_chunks(out))
    sec = dict(id="checks", heading="Checks", generator="checks", queries=["counter reload zero"])
    ctx = section_context(G, layered_view(G), sec, "tmr32", DocConfig(), slim=build_index(out))
    assert set(ctx) == {"queries", "requirements", "chunks", "dependencies"}
    assert ctx["requirements"] == [] and ctx["dependencies"] == []
    assert ctx["chunks"] and any(c.get("source") == "slim" for c in ctx["chunks"])


def test_slim_entries_schema_requires_quote():
    from dv_agent.plan.testplan_doc import _entries_schema

    slim = _entries_schema(None, [], ["CH-1"], slim=True)
    item = slim["properties"]["entries"]["items"]
    assert "quote" in item["required"] and "quote" in item["properties"]
    full = _entries_schema(None, ["REQ-x"], ["CH-1"])
    assert "quote" not in full["properties"]["entries"]["items"]["required"]


def test_validate_entries_verifies_slim_quotes(spec_repo, tmp_path):
    from dv_agent.graph.graph import build_structure
    from dv_agent.ingest.ingest import load_chunks, load_manifest
    from dv_agent.pipeline import run_ingest
    from dv_agent.plan.testplan_doc import _validate_entries

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    G = build_structure(load_manifest(out), load_chunks(out))
    cid = next(n for n, d in G.nodes(data=True) if d.get("type") == "chunk")
    quote = " ".join(G.nodes[cid]["text"].split()[:12])
    assert len(quote) >= 8
    good = dict(text="Check it", kind="check", provenance="DOCUMENTED", inference_reason="",
                cited_req_ids=[], cited_chunk_ids=[cid], details=[], quote=quote)
    bad = dict(good, quote="no such words exist here zz")
    missing = dict(good, quote="")
    rtl = dict(good, quote="", cited_rtl_observation_ids=["OBS-1"])
    entries = _validate_entries(G, [good, bad, missing, rtl], set(), {cid}, 10, ["OBS-1"])
    assert entries[0]["validation"] == [] and entries[0]["quote"] in G.nodes[cid]["text"]
    assert any("verbatim" in v for v in entries[1]["validation"])
    assert any("missing verbatim" in v for v in entries[2]["validation"])
    assert entries[3]["quote"] == "" and not any("quote" in v for v in entries[3]["validation"])


SLIM_KINDS = {"feature_description": "purpose", "strategy": "uvm_agent", "verification_plan": "sequence_implementation", "stimulus": "directed_test",
              "checks": "agent_scoreboard", "coverage": "covergroup", "callouts": "reuse",
              "assumptions": "assumption", "questions": "question"}


def slim_entries_handler(payload):
    sec = payload["section"]["id"]
    entries = []
    for c in payload["chunks"][:2]:
        words = c["text"].split()
        if len(words) < 6:
            continue
        entries.append({"text": f"{sec} entry backed by evidence", "kind": SLIM_KINDS[sec],
                        "provenance": "DOCUMENTED", "inference_reason": "",
                        "cited_req_ids": [r["req_id"] for r in payload.get("requirements", [])],
                        "cited_chunk_ids": [c["chunk_id"]], "details": [],
                        "quote": " ".join(words[:10])})
    if not entries:
        entries.append({"text": f"{sec} placeholder", "kind": SLIM_KINDS[sec], "provenance": "ASSUMED",
                        "inference_reason": "", "cited_req_ids": [], "cited_chunk_ids": [], "details": []})
    return {"entries": entries}


@pytest.fixture
def extracted_run(spec_repo, tmp_path):
    from dv_agent.pipeline import run_build_graph, run_ingest

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(), mode="graph")
    return out


def test_basic_testplan_reuses_prebuilt_requirements(extracted_run):
    from dv_agent.graph.graph import load_graph
    from dv_agent.pipeline import GRAPH_FILE, run_testplan_doc

    before = {n for n, d in load_graph(extracted_run / GRAPH_FILE).nodes(data=True) if d.get("type") == "requirement"}
    llm = _llm(testplan_entries=slim_entries_handler)
    result = run_testplan_doc(extracted_run, llm, mode="basic")
    assert not any(name == "requirement_dependencies" for name, _ in llm.calls)
    assert result["reused"] is False
    doc = _doc(extracted_run)
    assert doc["mode"] == "basic"
    assert [s["status"] for s in doc["sections"]] == ["PASS"] * 3 + ["NOT_RUN"] + ["PASS"] * 9
    G = load_graph(extracted_run / GRAPH_FILE)
    reqs = [n for n, d in G.nodes(data=True) if d.get("type") == "requirement"]
    assert reqs
    assert set(reqs) == before
    cited = {r for s in doc["sections"] for e in s.get("entries", []) for r in e["cited_req_ids"]}
    assert cited and cited <= set(reqs)


def test_testplan_reuse_respects_mode(spec_repo, tmp_path):
    from dv_agent.pipeline import run_build_graph, run_ingest, run_testplan_doc

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(), mode="graph")
    run_testplan_doc(out, _llm(), mode="graph")
    assert _doc(out)["mode"] == "graph"
    basic = run_testplan_doc(out, _llm(testplan_entries=slim_entries_handler), mode="basic")
    assert basic["reused"] is False and _doc(out)["mode"] == "basic"
    again = run_testplan_doc(out, _llm(testplan_entries=slim_entries_handler), mode="basic")
    assert again["reused"] is True


def test_basic_plan_uses_chunks_and_reports_reduced_analysis(spec_repo, tmp_path):
    out = tmp_path / "basic"
    llm = _llm(testplan_entries=slim_entries_handler)
    run_ingest(spec_repo, out)
    run_build_graph(out, llm, mode="basic")
    llm.calls.clear()
    run_testplan_doc(out, llm, mode="basic")
    doc = _doc(out)
    assert doc["mode"] == "basic" and "no extracted requirement" in doc["analysis_scope"]
    assert not any(name in ("spec_requirements", "requirement_dependencies", "testplan_claims") for name, _ in llm.calls)
    assert doc["registers"]["registers"]
    assert (out / "testplan_doc.html").is_file()
    assert "Basic RAG demo draft" in (out / "testplan_doc.md").read_text()
    assert run_testplan_doc(out, llm, mode="basic")["reused"]


def _cited_entry(**over):
    entry = dict(text="Exercise the reload path.", kind="check", provenance="DOCUMENTED",
                 inference_reason="", cited_req_ids=["REQ-1"], cited_chunk_ids=["CH-1"],
                 cited_rtl_observation_ids=[], cited_methodology_ids=[], details=[], validation=[])
    entry.update(over)
    return entry


def test_entry_tables_and_configurations_keep_document_markers():
    from dv_agent.plan.testplan_doc import (_described, _render_configurations, _render_entry,
                                            _render_table)
    marker = "📄<!--dv-sources:REQ-1,CH-1-->"
    entry = _cited_entry()
    assert marker in _render_entry(entry, indicator_last=True)[0]
    assert marker in "\n".join(_render_table([entry]))
    assert marker in _described(entry, [])
    config = dict(entry, register="CTRL", field="Enable", bits="0", access="RW", randomize=True,
                  legal_values=["0", "1"], distribution="", constraints=[], reserved_handling="",
                  notes="")
    assert marker in "\n".join(_render_configurations(dict(configurations=[config], validation=[])))


def test_section_provenance_strips_badges_but_keeps_markers():
    from dv_agent.plan.testplan_doc import _section_provenance
    from dv_agent.report.provenance_badge import badge, cite_marker
    item = f"- {badge('DOCUMENTED', ['CH-1'], '')} text{cite_marker(['CH-1'])}"
    out = _section_provenance("## Feature Description\n\n" + item + "\n")
    assert "## Feature Description ✅<!--dv-evidence:" in out
    assert "📄<!--dv-sources:CH-1-->" in out
    assert out.count("✅<!--dv-evidence:") == 1


def test_coverage_lists_carry_document_markers():
    from dv_agent.plan.testplan_doc import _render_coverage
    cov = dict(total=1, covered=0, ratio=0.0, chunk_only=[],
               uncovered=[dict(req_id="REQ-7", section="2 Registers", page=2, statement="Reload works.")])
    assert "📄<!--dv-sources:REQ-7-->" in "\n".join(_render_coverage(cov))


def test_references_appendix_covers_marker_only_ids():
    from dv_agent.plan.testplan_doc import _render_references
    index = {"CH-9": dict(path="doc/spec.txt", section="S", page=1, excerpt="The thing works.")}
    out = _render_references("- text 📄<!--dv-sources:CH-9-->\n", index)
    assert "### Reference CH-9" in out and "The thing works." in out


def test_evidence_index_covers_rtl_excerpts_and_methodology_rules():
    import networkx as nx
    from dv_agent.plan.testplan_doc import build_evidence_index
    doc = dict(sections=[],
               rtl_observations=dict(
                   evidence=[dict(id="EX-1", path="rtl/top.sv", line_start=3, line_end=5,
                                  text="always @(posedge clk) q <= d;")],
                   entries=[]),
               methodology_rules=[dict(id="METH-X", statement="Never sample an unknown value.")])
    index = build_evidence_index(nx.MultiDiGraph(), doc)
    assert index["EX-1"]["excerpt"].startswith("always @(posedge clk)")
    assert index["EX-1"]["line_start"] == 3
    assert index["METH-X"]["excerpt"] == "Never sample an unknown value."
    assert index["METH-X"]["path"] == "Methodology rules"


def test_every_assertion_needs_a_label_and_a_paired_cover_property():
    from dv_agent.plan.testplan_doc import pairing_problems, render_markdown, unpaired_assertions

    def entry(text, kind, details=()):
        return {"text": text, "kind": kind, "details": list(details), "provenance": "DOCUMENTED", "cited_req_ids": [],
                "cited_chunk_ids": ["CH-1"], "cited_rtl_observation_ids": [], "validation": []}

    checks = [entry("ack follows req: a_ack_after_req", "assertion"), entry("data stays stable: a_stable", "assertion"),
              entry("monitor flags X", "protocol_check"), entry("unlabelled handshake rule", "assertion")]
    covers = [entry("cover c_ack_after_req", "cover_property"), entry("covergroup", "covergroup")]
    assert unpaired_assertions(checks, covers) == (["a_stable"], 1)
    sections = [{"id": "checks", "entries": checks}]
    assert pairing_problems("coverage", covers, sections) == [
        "assertion a_stable has no cover_property entry; add one named c_stable with a_stable in its details"]
    assert "no label" in pairing_problems("checks", checks, [])[0] and pairing_problems("stimulus", checks, []) == []
    # a cover that names the assertion label in its details counts as paired
    covers.append(entry("cover the stable rule", "cover_property", ["Assertion: a_stable"]))
    assert pairing_problems("coverage", covers, sections) == []
    md = render_markdown({"sections": [dict(id="checks", heading="8", generator="entries", status="PASS", entries=checks),
                                       dict(id="coverage", heading="9", generator="entries", status="PASS", entries=covers[:1] + covers[1:2])],
                          "coverage": None, "token_usage": None})
    assert "Assertions without a paired cover property: a_stable" in md
