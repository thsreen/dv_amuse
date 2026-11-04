import json

from conftest import interfaces_handler
from dv_agent.graph.graph import lineage, load_graph
from dv_agent.plan.interfaces import UNGROUPED, compact, extract_interfaces
from dv_agent.core.llm import LLMError
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_testplan_doc
from dv_agent.retrieval.retrieval import layered_view
from dv_agent.core.trace import Tracer
from test_testplan_doc import _llm, entries_handler


def _graph(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(), mode="graph")
    return out, load_graph(out / GRAPH_FILE)


def _extract(G, tmp_path, llm=None):
    with Tracer(tmp_path / "t.jsonl", "t") as tracer:
        return extract_interfaces(G, layered_view(G), llm or _llm(), tracer)


def test_signals_are_verified_against_the_spec(spec_repo, tmp_path):
    _, G = _graph(spec_repo, tmp_path)
    res = _extract(G, tmp_path)
    names = {s["name"]: s for s in res["signals"]}
    assert "GHOST_SIG" not in names
    assert any("GHOST_SIG" in v and "not found" in v for v in res["validation"])
    assert names["BUS_RDATA"]["direction"] == "output" and names["BUS_RDATA"]["direction_documented"]
    assert names["BUS_WDATA"]["width_documented"] and names["BUS_WDATA"]["provenance"] == "DOCUMENTED"
    assert names["TICK_O"]["availability"] == "TMR_HAS_TICK defined"


def test_interface_metadata_is_bulleted_with_collapsed_quotes(spec_repo, tmp_path):
    from dv_agent.plan.interfaces import render
    from dv_agent.report.html_report import render_html
    _, G = _graph(spec_repo, tmp_path)
    result = _extract(G, tmp_path)
    md = "\n".join(render(result, "Interfaces"))
    assert "- Function:" in md and "- DUT role:" in md
    assert " | Category:" not in md
    assert "<summary>Specification evidence</summary>" in md
    header_at = md.index("### ")
    info_at = md.index("<summary>ⓘ Interface info</summary>")
    assert header_at < info_at < md.index("- Function:")
    assert md.index("</details>", info_at) < md.index("| Signal |")
    report = render_html(md)
    assert '<details class="interface-info"><summary>ⓘ Interface info</summary>' in report
    assert '<details class="interface-info" open' not in report
    assert '<details class="source-quotes"><summary>Specification evidence</summary>' in report
    assert '<details class="source-quotes" open' not in report
    assert '<blockquote>' in report
    assert "| Source |" not in md
    fields = {"name", "width", "direction", "active_level", "availability", "description"}
    saved = json.loads(json.dumps(result))
    for group in saved["groups"]:
        for signal in group["signals"]:
            assert fields <= signal.keys()
            assert fields == signal["documented"].keys()
            row = next(line for line in md.splitlines() if line.startswith(f"| {signal['name']} |"))
            assert row.count("|") == 7  # six columns; the Source column was removed


def test_every_signal_in_exactly_one_group(spec_repo, tmp_path):
    _, G = _graph(spec_repo, tmp_path)
    res = _extract(G, tmp_path)
    placed = [s["name"] for g in res["groups"] for s in g["signals"]]
    assert sorted(placed) == sorted(s["name"] for s in res["signals"]) and len(placed) == len(set(placed))
    groups = {g["name"]: g for g in res["groups"]}
    assert [s["name"] for s in groups["Reset"]["signals"]] == ["RST_N"]
    assert any("CLK already in another group" in v for v in res["validation"])
    ungrouped = groups[UNGROUPED]
    assert [s["name"] for s in ungrouped["signals"]] == ["TICK_O"] and ungrouped["provenance"] == "ASSUMED"


def test_groups_are_inferred_with_direction_and_peer(spec_repo, tmp_path):
    _, G = _graph(spec_repo, tmp_path)
    groups = {g["name"]: g for g in _extract(G, tmp_path)["groups"]}
    assert all(g["provenance"] in ("INFERRED", "ASSUMED") for g in groups.values())
    assert groups["Register bus"]["direction_summary"] == "both directions"
    assert groups["Clock"]["direction_summary"] == "into DUT"
    irq = groups["Interrupt"]
    assert irq["direction_summary"] == "out of DUT" and irq["is_sideband"] and irq["connected_to"] == "interrupt controller"
    bus = next(c for c in compact({"groups": list(groups.values())}) if c["group"] == "Register bus")
    assert "BUS_RDATA[32] output" in bus["signals"]


def test_interfaces_come_first_and_feed_every_section(spec_repo, tmp_path):
    out, _ = _graph(spec_repo, tmp_path)
    seen = {}

    def capture(payload):
        seen[payload["section"]["id"]] = payload["interfaces"]
        return entries_handler(payload)
    summary = run_testplan_doc(out, _llm(testplan_entries=capture), mode="graph")
    assert summary["interfaces"]["status"] == "PASS"
    assert {g["group"] for g in seen["stimulus"]} >= {"Register bus", "Interrupt"}
    assert all(seen[s] == seen["stimulus"] for s in seen)
    md = (out / "testplan_doc.md").read_text()
    assert md.index("## 1.1 Interface Definitions") < md.index("## 2. Feature Description")
    assert "| TICK_O | 1 | output | — | TMR_HAS_TICK defined |" in md
    doc = json.loads((out / "testplan_doc.json").read_text())
    questions = next(s for s in doc["sections"] if s["id"] == "questions")["entries"]
    assert any("TICK_O" in q["text"] and "Which interface" in q["text"] for q in questions)
    G = load_graph(out / GRAPH_FILE)
    art = doc["interfaces"]["artifact_id"]
    assert G.nodes[art]["type"] == "interface_definitions"
    assert lineage(G, art)["sources"]


def test_blocked_interface_step_stops_all_following_model_work(spec_repo, tmp_path):
    out, _ = _graph(spec_repo, tmp_path)

    def failing(payload):
        raise LLMError("transient", "simulated")
    llm = _llm(testplan_interfaces=failing)
    summary = run_testplan_doc(out, llm, mode="graph")
    assert summary["interfaces"]["status"] == "BLOCKED"
    status = {s["id"]: s["status"] for s in summary["sections"]}
    for name in ("strategy", "verification_plan", "stimulus", "checks", "coverage", "callouts"):
        assert status[name] == "BLOCKED"
    assert set(status.values()) == {"BLOCKED"}
    assert summary["registers"]["status"] == "BLOCKED"
    assert not any(name in ("testplan_registers", "testplan_entries", "testplan_strategy", "testplan_configurations")
                   for name, _ in llm.calls)
    assert summary["status"] == "BLOCKED"
    assert "**BLOCKED**" in (out / "testplan_doc.md").read_text()
    assert run_testplan_doc(out, _llm(), mode="graph")["reused"] is False


def test_interface_step_can_be_disabled_in_template(spec_repo, tmp_path):
    from dv_agent.plan.testplan_doc import DEFAULT_TEMPLATE
    out, _ = _graph(spec_repo, tmp_path)
    t = json.loads(DEFAULT_TEMPLATE.read_text())
    t["interfaces"] = {"enabled": False}
    path = tmp_path / "no_iface.json"
    path.write_text(json.dumps(t))
    llm = _llm()
    summary = run_testplan_doc(out, llm, template_path=path, mode="graph")
    assert summary["interfaces"] is None and not any(name == "testplan_interfaces" for name, _ in llm.calls)


def test_grouping_key_is_functionality_and_connected_module_type(spec_repo, tmp_path):
    _, G = _graph(spec_repo, tmp_path)
    groups = {g["name"]: g for g in _extract(G, tmp_path)["groups"]}
    assert groups["Interrupt"]["peer_type"] == "interrupt_controller"
    assert groups["Interrupt"]["grouping_key"] == "interrupt|interrupt_controller"
    bus = groups["Register bus"]
    assert {s["direction"] for s in bus["signals"]} == {"input", "output"}  # direction is not a grouping key
    assert compact({"groups": [bus]})[0]["peer_type"] == "processor_or_bus_master"


def test_groups_sharing_functionality_and_module_type_are_flagged(spec_repo, tmp_path):
    _, G = _graph(spec_repo, tmp_path)

    def split_irq(payload):
        data = interfaces_handler(payload)
        tick = dict(next(g for g in data["groups"] if g["name"] == "Interrupt"), name="Tick", signals=["TICK_O"])
        data["groups"].append(tick)
        return data
    res = _extract(G, tmp_path, _llm(testplan_interfaces=split_irq))
    assert any("share functionality and connected module type (interrupt|interrupt_controller)" in v
               for v in res["validation"])
    assert UNGROUPED not in {g["name"] for g in res["groups"]}


def test_markdown_shows_connected_module_type(spec_repo, tmp_path):
    out, _ = _graph(spec_repo, tmp_path)
    run_testplan_doc(out, _llm(), mode="graph")
    md = (out / "testplan_doc.md").read_text()
    assert "Connected module type: interrupt_controller" in md
    assert "Connected to: interrupt controller" in md


def test_active_level_is_checked_against_the_quote(spec_repo, tmp_path):
    _, G = _graph(spec_repo, tmp_path)
    res = _extract(G, tmp_path)
    sigs = {s["name"]: s for s in res["signals"]}
    assert sigs["RST_N"]["active_level"] == "low" and sigs["RST_N"]["active_level_documented"]
    assert sigs["IRQ"]["active_level"] == "high" and not sigs["IRQ"]["active_level_documented"]
    from dv_agent.plan.interfaces import interface_questions
    qs = [q["text"] for q in interface_questions(res)]
    assert any("active level of IRQ" in q for q in qs) and not any("active level of RST_N" in q for q in qs)
    bus = next(c for c in compact(res) if c["group"] == "Reset")
    assert bus["signals"] == ["RST_N[1] input active-low"]


def test_interface_chunks_slim_returns_cited_chunks(spec_repo, tmp_path):
    from dv_agent.graph.graph import build_structure
    from dv_agent.ingest.ingest import load_chunks, load_manifest
    from dv_agent.plan.interfaces import InterfaceConfig, interface_chunks
    from dv_agent.pipeline import run_ingest
    from dv_agent.retrieval.slim_index import build_index

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    G = build_structure(load_manifest(out), load_chunks(out))
    chunks = interface_chunks(G, layered_view(G), "tmr32", InterfaceConfig(), slim=build_index(out))
    assert chunks and any(c.get("source") == "slim" for c in chunks)
    assert all({"chunk_id", "text", "score", "doc_path", "pages"} <= set(c) for c in chunks)


def test_interfaces_basic_mode_marks_and_reuses(spec_repo, tmp_path):
    import json

    from dv_agent.pipeline import run_build_graph, run_ingest, run_interfaces
    from test_testplan_doc import _llm

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(), mode="basic")
    first = run_interfaces(out, _llm(), mode="basic")
    assert first["status"] == "PASS" and first["reused"] is False
    assert json.loads((out / "interfaces.json").read_text())["mode"] == "basic"
    assert run_interfaces(out, _llm(), mode="basic")["reused"] is True
    assert run_interfaces(out, _llm(), mode="graph")["reused"] is False


def test_interface_sources_use_document_markers(spec_repo, tmp_path):
    import re
    from dv_agent.plan.interfaces import render
    _, G = _graph(spec_repo, tmp_path)
    md = "\n".join(render(_extract(G, tmp_path), "Interfaces"))
    assert "📄<!--dv-sources:" in md
    assert re.search(r"Source: `[^`]+`, CH-", md) is None
    signal_row = next(line for line in md.splitlines() if line.startswith("| CLK |"))
    assert "📄<!--dv-sources:" in signal_row


def test_testbench_supplied_clock_and_reset_raise_plan_time_questions_when_undocumented():
    from dv_agent.plan.interfaces import interface_questions

    def group(name, category, signals):
        return dict(name=name, category=category, signals=[
            dict(name=n, direction=d, direction_documented=True, active_level_documented=documented) for n, d, documented in signals])
    groups = [group("clk", "clock", [("CLK", "input", False)]), group("rst", "reset", [("RST", "input", False)]),
              group("tick", "clock", [("TICK", "output", False)]), group("clk2", "clock", [("CLK2", "input", True)])]
    texts = [q["text"] for q in interface_questions({"groups": groups})]
    assert any(t.startswith("What is the active edge of CLK ") for t in texts)  # a clock the testbench supplies
    assert any(t.startswith("What is the active level of RST ") for t in texts)
    assert not any("TICK" in t or "CLK2" in t for t in texts)  # a derived clock output or a documented edge needs none


def test_a_condition_is_found_whatever_its_capitalization_or_line_breaks_unless_negated():
    from dv_agent.plan.interfaces import condition_stated
    source = "BAUD_O 1 Output Optional baud rate output signal.\nIt is enabled if UART_HAS_BAUDRATE_OUTPUT\nis defined\n"
    assert condition_stated(source, "Enabled if UART_HAS_BAUDRATE_OUTPUT is defined")
    assert condition_stated(source, "enabled if UART_HAS_BAUDRATE_OUTPUT is defined")
    assert not condition_stated(source, "Enabled if SOMETHING_ELSE is defined")
    assert not condition_stated(source, "")
    assert not condition_stated("It is not enabled if FEATURE_X is defined", "Enabled if FEATURE_X is defined")

