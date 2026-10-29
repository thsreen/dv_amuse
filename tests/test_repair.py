import json

import pytest

from dv_agent.graph import load_graph
from dv_agent.llm import FakeLLM, LLMError
from dv_agent.pipeline import run_build_graph, run_ingest, run_registers, run_testplan_doc
from dv_agent.registers import record_problems
from dv_agent.repair import default_max_repairs, structured_with_repair
from dv_agent.trace import Tracer, read_trace
from test_registers import SPEC, handler as register_handler
from test_testplan_doc import _llm, configurations_handler, strategy_handler


def _tracer(tmp_path):
    return Tracer(tmp_path / "t.jsonl", "t")


def test_refusal_feedback_reaches_the_model_and_the_repair_is_accepted(tmp_path):
    def h(payload):
        return {"x": "good"} if "refusal" in payload else {"x": "bad"}
    llm = FakeLLM({"step": h})
    with _tracer(tmp_path) as tracer:
        out = structured_with_repair(llm, tracer, name="step", instructions="i", payload={"p": 1}, schema={},
                                     check=lambda d: ["x must be good"] if d["x"] != "good" else [])
    assert out.data == {"x": "good"} and out.attempts == 2 and out.unresolved == []
    assert out.history == [{"attempt": 1, "problems": ["x must be good"]}]
    second = llm.calls[1][1]
    assert second["previous_output"] == {"x": "bad"} and second["refusal"] == ["x must be good"] and second["p"] == 1
    spans = [r["name"] for r in read_trace(tmp_path / "t.jsonl")]
    assert "refusal:step" in spans


def test_repair_budget_and_zero_budget(tmp_path):
    always_bad = FakeLLM({"step": lambda p: {"x": "bad"}})
    with _tracer(tmp_path) as tracer:
        out = structured_with_repair(always_bad, tracer, name="step", instructions="i", payload={}, schema={},
                                     check=lambda d: ["still bad"], max_repairs=2)
        none = structured_with_repair(always_bad, tracer, name="step", instructions="i", payload={"q": 1}, schema={},
                                      check=lambda d: ["still bad"], max_repairs=0)
    assert out.attempts == 3 and len(out.history) == 2 and out.unresolved == ["still bad"]
    assert none.attempts == 1 and none.history == [] and none.unresolved == ["still bad"]


def test_failed_repair_call_keeps_last_answer(tmp_path):
    def h(payload):
        if "refusal" in payload:
            raise LLMError("transient", "simulated")
        return {"x": "bad"}
    with _tracer(tmp_path) as tracer:
        out = structured_with_repair(FakeLLM({"step": h}), tracer, name="step", instructions="i", payload={},
                                     schema={}, check=lambda d: ["bad"])
    assert out.data == {"x": "bad"} and out.repair_error == "transient" and out.unresolved == ["bad"]


def test_max_repairs_setting_is_validated(monkeypatch):
    monkeypatch.setenv("DV_AGENT_MAX_REPAIRS", "many")
    with pytest.raises(ValueError):
        default_max_repairs()
    monkeypatch.setenv("DV_AGENT_MAX_REPAIRS", "1")
    assert default_max_repairs() == 1


@pytest.fixture
def reg_run(tmp_path):
    repo = tmp_path / "blk"
    (repo / "doc").mkdir(parents=True)
    (repo / "doc" / "spec.md").write_text(SPEC)
    out = tmp_path / "run"
    run_ingest(repo, out)
    run_build_graph(out, None)
    return out


def test_register_step_refuses_invented_values_and_keeps_spec_conflicts(reg_run):
    def invent_then_fix(payload):
        data = register_handler(payload)
        data["registers"] = [r for r in data["registers"] if r["abbreviation"] != "PHM"]
        if "refusal" not in payload:
            for r in data["registers"]:
                for f in r["fields"]:
                    if f["name"] == "Mode select":
                        f["values"] = [dict(value="1111", meaning="invented")]
        else:
            for r in data["registers"]:
                if r["width"] == "8":
                    r["width"] = ""  # the chunk never states a width
                for f in r["fields"]:
                    if f["name"] == "Mode select":
                        f["values"] = []
        return data
    run_registers(reg_run, FakeLLM({"testplan_registers": invent_then_fix}))
    res = json.loads((reg_run / "registers.json").read_text())
    refusals = res["repair"]["refusals"]
    assert refusals and any("'1111' is not written" in p for r in refusals for p in r["problems"])
    assert res["repair"]["unresolved"] == []
    assert res["conflicts"], "the spec conflict (reset 00h vs 01h) is reported, not refused"
    assert not any("reset_value" in p and "01h" in p for r in refusals for p in r["problems"])
    assert "Repaired after 1 refusal(s)." in (reg_run / "registers.md").read_text()


def test_record_problems_only_lists_model_fixable_issues(reg_run):
    G = load_graph(reg_run / "graph.json")
    cids = {n for n, d in G.nodes(data=True) if d.get("type") == "chunk"}
    payload = {"chunks": [{"chunk_id": c, "text": G.nodes[c]["text"]} for c in sorted(cids)]}
    problems = record_problems(G, register_handler(payload), cids)
    listing = next(c for c in cids if "Register list" in G.nodes[c]["text"])
    detail = next(c for c in cids if "CTRL register" in G.nodes[c]["text"])
    assert sorted(problems) == sorted([
        f"register PHANTOM: name not found in chunk {listing}",
        f"register CTRL: width '8' is not written in chunk {detail}; copy it exactly or use \"\"",
        f"CTRL.Mode select: value '0000' is not written in chunk {detail}"])
    assert not any("reset_value" in p for p in problems)  # 00h vs 01h is a spec conflict, not a model error


@pytest.fixture
def doc_run(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm())
    return out


def fixed_strategy(payload):
    data = strategy_handler(payload)
    if "refusal" not in payload:
        return data
    data["agents"][0]["drives"] = ["BUS_ADDR", "BUS_WDATA", "BUS_WE"]
    data["agents"][0]["monitors"] = ["BUS_RDATA"]
    data["agents"][1]["drives"] = []
    data["agents"][1]["correctness"] = [{"mechanism": "monitor_check", "description": "IRQ only when counter is zero"}]
    data["agents"][2]["interface_groups"] = ["Clock", "Reset"]
    data["agents"].append({"name": "misc_agent", "interface_groups": ["Ungrouped signals"], "mode": "passive",
                           "role": "tick monitor", "drives": [], "monitors": ["TICK_O"], "registers": [],
                           "sequences": [], "correctness": [{"mechanism": "coverage", "description": "tick seen"}],
                           "cited_chunk_ids": []})
    data["scoreboards"][0]["inputs"] = ["bus_agent", "irq_agent"]
    data["virtual_sequences"][0]["agents"] = ["clk_rst_agent", "bus_agent"]
    return data


def test_strategy_is_repaired_after_refusal(doc_run):
    run_testplan_doc(doc_run, _llm(testplan_strategy=fixed_strategy))
    doc = json.loads((doc_run / "testplan_doc.json").read_text())
    st = next(s for s in doc["sections"] if s["id"] == "strategy")["strategy"]
    assert st["validation"] == [] and st["gaps"] == []
    assert len(st["repair"]["refusals"]) == 1 and st["repair"]["unresolved"] == []
    assert any("a DUT output" in p for p in st["repair"]["refusals"][0]["problems"])
    md = (doc_run / "testplan_doc.md").read_text()
    assert "> Refused (attempt 1):" in md and "> Repaired after 1 refusal(s)." in md
    questions = next(s for s in doc["sections"] if s["id"] == "questions")["entries"]
    assert not any("High Level Verification Strategy step could not be completed" in q["text"] for q in questions)


def test_unrepaired_strategy_problems_become_one_designer_question(doc_run):
    run_testplan_doc(doc_run, _llm())
    doc = json.loads((doc_run / "testplan_doc.json").read_text())
    st = next(s for s in doc["sections"] if s["id"] == "strategy")["strategy"]
    assert len(st["repair"]["refusals"]) == 2 and st["repair"]["unresolved"]
    questions = [q["text"] for q in next(s for s in doc["sections"] if s["id"] == "questions")["entries"]]
    strategy_qs = [q for q in questions if "High Level Verification Strategy step could not be completed" in q]
    assert len(strategy_qs) == 1 and "after 2 repair attempt(s)" in strategy_qs[0]
    assert "is not covered by any agent" not in strategy_qs[0]  # already asked as its own question


def test_configurations_missing_field_is_refused_then_supplied(doc_run):
    def complete_on_refusal(payload):
        data = configurations_handler(payload)
        if "refusal" in payload:
            second = payload["configurable_fields"][1]["field_id"]
            data["configurations"] = [data["configurations"][0], dict(
                data["configurations"][0], field_id=second, legal_values=["0", "1"], randomize=True)]
        return data
    run_testplan_doc(doc_run, _llm(testplan_configurations=complete_on_refusal))
    doc = json.loads((doc_run / "testplan_doc.json").read_text())
    conf = next(s for s in doc["sections"] if s["id"] == "configurations")
    assert all(e["provenance"] != "ASSUMED" for e in conf["configurations"])
    problems = conf["repair"]["refusals"][0]["problems"]
    assert any("duplicate" in p for p in problems) and any("missing from model output" in p for p in problems)
    assert conf["repair"]["unresolved"] == []
