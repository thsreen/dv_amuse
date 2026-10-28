import json

from conftest import interfaces_handler
from dv_agent.graph import lineage, load_graph
from dv_agent.interfaces import UNGROUPED, compact, extract_interfaces
from dv_agent.llm import LLMError
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_testplan_doc
from dv_agent.retrieval import layered_view
from dv_agent.trace import Tracer
from test_testplan_doc import _llm, entries_handler


def _graph(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm())
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
    summary = run_testplan_doc(out, _llm(testplan_entries=capture))
    assert summary["interfaces"]["status"] == "PASS"
    assert {g["group"] for g in seen["strategy"]} >= {"Register bus", "Interrupt"}
    assert all(seen[s] == seen["strategy"] for s in seen)
    md = (out / "testplan_doc.md").read_text()
    assert md.index("## Interface Definitions") < md.index("## 2. Feature Description")
    assert "| TICK_O | 1 | output | TMR_HAS_TICK defined |" in md
    doc = json.loads((out / "testplan_doc.json").read_text())
    questions = next(s for s in doc["sections"] if s["id"] == "questions")["entries"]
    assert any("TICK_O" in q["text"] and "Which interface" in q["text"] for q in questions)
    G = load_graph(out / GRAPH_FILE)
    art = doc["interfaces"]["artifact_id"]
    assert G.nodes[art]["type"] == "interface_definitions"
    assert lineage(G, art)["sources"]


def test_blocked_interface_step_does_not_stop_the_plan(spec_repo, tmp_path):
    out, _ = _graph(spec_repo, tmp_path)

    def failing(payload):
        raise LLMError("transient", "simulated")
    summary = run_testplan_doc(out, _llm(testplan_interfaces=failing))
    assert summary["interfaces"]["status"] == "BLOCKED"
    assert all(s["status"] == "PASS" for s in summary["sections"])
    assert "**BLOCKED**" in (out / "testplan_doc.md").read_text()
    assert run_testplan_doc(out, _llm())["reused"] is False


def test_interface_step_can_be_disabled_in_template(spec_repo, tmp_path):
    from dv_agent.testplan_doc import DEFAULT_TEMPLATE
    out, _ = _graph(spec_repo, tmp_path)
    t = json.loads(DEFAULT_TEMPLATE.read_text())
    t["interfaces"] = {"enabled": False}
    path = tmp_path / "no_iface.json"
    path.write_text(json.dumps(t))
    llm = _llm()
    summary = run_testplan_doc(out, llm, template_path=path)
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
    run_testplan_doc(out, _llm())
    md = (out / "testplan_doc.md").read_text()
    assert "Connected module type: interrupt_controller (interrupt controller)" in md
