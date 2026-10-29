import json

import pytest

from dv_agent.cli import main
from dv_agent.llm import LLMError
from dv_agent.pipeline import run_build_graph, run_ingest, run_strategy, run_testplan_doc
from test_testplan_doc import _llm


@pytest.fixture
def run(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm())
    return out


def _strategy(out):
    run_testplan_doc(out, _llm())
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


def test_uncovered_interface_group_is_a_gap_and_a_question(run):
    doc, st = _strategy(run)
    assert [g["interface_group"] for g in st["gaps"]] == ["Ungrouped signals"]
    questions = next(s for s in doc["sections"] if s["id"] == "questions")["entries"]
    assert any("Ungrouped signals" in q["text"] and "assigns no agent" in q["text"] for q in questions)
    md = (run / "testplan_doc.md").read_text()
    assert "### Agents" in md and "| bus_agent | Register bus | active | BUS_ADDR, BUS_WDATA, BUS_WE |" in md
    assert "- Correctness (agent_scoreboard): read data matches the register model" in md


def test_standalone_strategy_uses_documented_steps_and_reuses(run):
    first = run_strategy(run, _llm())
    assert first["reused"] is False and first["inputs"] == {"interfaces": False, "registers": False}
    assert (run / "interfaces.json").exists() and (run / "registers.json").exists() and (run / "strategy.md").exists()
    llm = _llm()
    second = run_strategy(run, llm)
    assert second["reused"] is True and second["inputs"] == {"interfaces": True, "registers": True}
    assert llm.calls == []
    (run / "registers.json").unlink()
    third = run_strategy(run, _llm())
    assert third["inputs"]["registers"] is False and third["reused"] is False
    saved = json.loads((run / "strategy.json").read_text())
    assert saved["registers_trace_id"] == json.loads((run / "registers.json").read_text())["trace_id"]


def test_strategy_not_run_without_interface_groups(run):
    def failing(payload):
        raise LLMError("transient", "simulated")
    result = run_strategy(run, _llm(testplan_interfaces=failing))
    assert result["status"] == "NOT_RUN" and "interface" in result["error"]


def test_cli_strategy(run, capsys, monkeypatch):
    from dv_agent import cli
    monkeypatch.setattr(cli, "_llm", _llm)
    assert main(["strategy", "--out", str(run)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {a["name"] for a in out["agents"]} == {"bus_agent", "irq_agent", "clk_rst_agent"}
    assert main(["interfaces", "--out", str(run)]) == 0
    assert json.loads(capsys.readouterr().out)["reused"] is True
