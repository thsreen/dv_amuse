import json

import pytest

from dv_agent.cli import main
from dv_agent.core.llm import LLMError
from dv_agent.pipeline import run_build_graph, run_ingest, run_strategy, run_testplan_doc
from test_testplan_doc import _llm


@pytest.fixture
def run(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(), mode="graph")
    return out


def _strategy(out):
    run_testplan_doc(out, _llm(), mode="graph")
    doc = json.loads((out / "testplan_doc.json").read_text())
    return doc, next(s for s in doc["sections"] if s["id"] == "strategy")["strategy"]


def test_agents_are_checked_against_interface_groups(run):
    _, st = _strategy(run)
    agents = {a["name"]: a for a in st["agents"]}
    bus = agents["bus_agent"]
    assert bus["drives"] == ["BUS_ADDR", "BUS_WDATA", "BUS_WE"] and bus["monitors"] == ["BUS_RDATA"]
    assert bus["registers"] == ["CTRL"] and bus["provenance"] == "INFERRED" and bus["cited_chunk_ids"]
    assert agents["irq_agent"]["drives"] == []
    assert agents["clk_rst_agent"]["interface_groups"] == ["Clock", "Reset", "Register bus"]
    notes = "\n".join(st["validation"])
    for expected in ("drives BUS_RDATA, a DUT output", "monitors ['IRQ'] not in its interface groups",
                     "irq_agent: drives IRQ, a DUT output", "irq_agent: no correctness mechanism stated",
                     "'Register bus' is assigned to both bus_agent and clk_rst_agent",
                     "unknown input agents ['ghost_agent']", "unknown agents ['nobody']"):
        assert expected in notes, expected


def test_scoreboards_register_model_and_virtual_sequences(run):
    _, st = _strategy(run)
    assert st["scoreboards"][0]["inputs"] == ["bus_agent", "irq_agent"] and st["scoreboards"][0]["level"] == "top"
    assert st["register_model"] == {"used": True, "registers": ["CTRL"], "description": "mirror checks on read"}
    assert st["virtual_sequences"][0]["agents"] == ["clk_rst_agent", "bus_agent"]


def test_source_supported_strategy_item_keeps_its_own_status(run):
    from test_testplan_doc import strategy_handler
    def supported(payload):
        data = strategy_handler(payload)
        source = payload["chunks"][0]
        # Model can report an explicit source requirement without being forced inferred by section.
        data["agents"][0]["correctness"][0].update(
            description=source["text"], support=dict(provenance="DOCUMENTED", quote=source["text"],
                                                    chunk_id=source["chunk_id"], inference_reason=""))
        return data
    run_testplan_doc(run, _llm(testplan_strategy=supported), mode="graph")
    doc = json.loads((run / "testplan_doc.json").read_text())
    st = next(s for s in doc["sections"] if s["id"] == "strategy")["strategy"]
    assert st["agents"][0]["provenance"] == "INFERRED"
    assert st["agents"][0]["correctness"][0]["provenance"] == "DOCUMENTED"
    assert "✅<!--dv-evidence:" in (run / "testplan_doc.md").read_text()


def test_overview_rendering_keeps_details_for_downstream_plan(run):
    from test_testplan_doc import strategy_handler
    from dv_agent.plan.strategy import render, strategy_summary
    def overview(payload):
        data = strategy_handler(payload)
        source = payload["chunks"][0]
        data["overview"] = [dict(text="Prioritize reset bring-up before constrained-random traffic.",
                                 support=dict(provenance="INFERRED", quote=source["text"],
                                              chunk_id=source["chunk_id"],
                                              inference_reason="Bring-up establishes a known starting state."))]
        return data
    run_testplan_doc(run, _llm(testplan_strategy=overview), mode="graph")
    doc = json.loads((run / "testplan_doc.json").read_text())
    st = next(s for s in doc["sections"] if s["id"] == "strategy")["strategy"]
    md = "\n".join(render(st, "High Level Verification Strategy"))
    assert "Prioritize reset bring-up" in md and "⚠️<!--dv-evidence:" in md
    assert "### Agents" not in md and "BUS_ADDR" not in md and "Sequence `" not in md
    assert st["agents"] and st["scoreboards"]  # downstream implementation context preserved
    assert any(line.startswith("Approach:") for line in strategy_summary(st))


def test_uncovered_interface_group_is_a_gap_and_a_question(run):
    doc, st = _strategy(run)
    assert [g["interface_group"] for g in st["gaps"]] == ["Ungrouped signals"]
    questions = next(s for s in doc["sections"] if s["id"] == "questions")["entries"]
    assert any("Ungrouped signals" in q["text"] and "assigns no agent" in q["text"] for q in questions)
    md = (run / "testplan_doc.md").read_text()
    assert "### Agents" in md and "Agent `bus_agent` (active)" in md
    assert "Drives: BUS_ADDR, BUS_WDATA, BUS_WE" in md
    assert "Correctness (agent_scoreboard) in `bus_agent`: read data matches the register model" in md


def test_every_strategy_bullet_has_its_own_evidence_status(run):
    import re
    from dv_agent.plan.strategy import render
    from dv_agent.report.provenance_badge import decode
    _, st = _strategy(run)
    lines = render(st, "Verification Strategy")
    assert not any(line.startswith("|") for line in lines)
    bullets = [line for line in lines if line.startswith("- ")]
    assert bullets
    states = []
    for line in bullets:
        match = re.match(r"- (?:✅|⚠️|🛑)<!--dv-evidence:([A-Za-z0-9_-]+)-->", line)
        assert match, line
        state = decode(match.group(1))
        states.append(state["state"])
        if state["state"] == "INFERRED":
            assert state["citations"] and state["reason"]
    assert "INFERRED" in states and "NO_REFERENCE" in states


def test_standalone_strategy_uses_documented_steps_and_reuses(run):
    first = run_strategy(run, _llm(), mode="graph")
    assert first["reused"] is False and first["inputs"] == {"interfaces": False, "registers": False}
    assert (run / "interfaces.json").exists() and (run / "registers.json").exists() and (run / "strategy.md").exists()
    llm = _llm()
    second = run_strategy(run, llm, mode="graph")
    assert second["reused"] is True and second["inputs"] == {"interfaces": True, "registers": True}
    assert llm.calls == []
    (run / "registers.json").unlink()
    third = run_strategy(run, _llm(), mode="graph")
    assert third["inputs"]["registers"] is False and third["reused"] is False
    saved = json.loads((run / "strategy.json").read_text())
    assert saved["registers_trace_id"] == json.loads((run / "registers.json").read_text())["trace_id"]


def test_strategy_not_run_without_interface_groups(run):
    def failing(payload):
        raise LLMError("transient", "simulated")
    result = run_strategy(run, _llm(testplan_interfaces=failing), mode="graph")
    assert result["status"] == "NOT_RUN" and "interface" in result["error"]


def test_cli_strategy(run, capsys, monkeypatch):
    from dv_agent import cli
    monkeypatch.setattr(cli, "_llm", _llm)
    assert main(["strategy", "--out", str(run)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {a["name"] for a in out["agents"]} == {"bus_agent", "irq_agent", "clk_rst_agent"}
    assert main(["interfaces", "--out", str(run)]) == 0
    assert json.loads(capsys.readouterr().out)["reused"] is True


def test_strategy_bullets_carry_document_markers(run):
    import re
    from dv_agent.plan.strategy import render
    from dv_agent.report.provenance_badge import decode
    _, st = _strategy(run)
    bullets = [line for line in render(st, "Verification Strategy") if line.startswith("- ")]
    assert bullets
    for line in bullets:
        match = re.match(r"- (?:✅|⚠️|🛑)<!--dv-evidence:([A-Za-z0-9_-]+)-->", line)
        assert match, line
        if decode(match.group(1))["citations"]:
            assert "📄<!--dv-sources:" in line, line
        else:
            assert "📄" not in line, line
