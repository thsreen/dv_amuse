"""Offline tests for the DV/RTL orchestrator: order, overrides, budgets, guards."""
import json
import time
from pathlib import Path

import pytest

from dv_agent.llm import FakeLLM
from orchestrator_agent import runner
from orchestrator_agent.cli import main as cli_main
from orchestrator_agent.flow import FlowError, load_flow, resolve_args, validate_flow
from orchestrator_agent.guards import KNOWN_FORBIDDEN, post_testplan_check, pre_tool_check
from orchestrator_agent.tools import SPEC, ToolSpec


def base_flow(**overrides):
    flow = {
        "version": 1, "name": "test",
        "steps": [
            {"id": "first", "tool": "stub_a", "agent": "dv", "args": {}},
            {"id": "second", "tool": "stub_b", "agent": "rtl", "args": {}},
        ],
        "policy": {},
        "forbidden": [{"id": rid, "title": title} for rid, title in KNOWN_FORBIDDEN.items()],
    }
    flow.update(overrides)
    return flow


def stub_registry(calls, behaviours=None):
    behaviours = behaviours or {}
    specs = {}
    for tool, agent in (("stub_a", "dv"), ("stub_b", "rtl"), ("uvm_build", "dv")):
        def make(tool):
            def run(args, ctx):
                calls.append((tool, dict(args), ctx.extra_prompt))
                behaviour = behaviours.get(tool, {})
                if "sleep" in behaviour:
                    time.sleep(behaviour["sleep"])
                return dict(status=behaviour.get("status", "PASS"),
                            summary=behaviour.get("summary", f"{tool} ok"),
                            files=list(behaviour.get("files", [])))
            return run
        specs[tool] = ToolSpec(agent, SPEC, False, make(tool))
    return specs


def write_flow(tmp_path, flow):
    path = tmp_path / "flow.json"
    path.write_text(json.dumps(flow), encoding="utf-8")
    return path


def test_validate_ok_and_defaults(tmp_path):
    flow = validate_flow(base_flow())
    assert flow["policy"]["max_total_tool_calls"] == 32
    assert flow["steps"][0]["timeout_s"] == 600
    assert load_flow(write_flow(tmp_path, base_flow()))["name"] == "test"


def test_validate_rejects_bad_flows():
    with pytest.raises(FlowError):
        validate_flow(base_flow(version=99))
    with pytest.raises(FlowError):
        validate_flow(base_flow(steps=[]))
    dup = base_flow()
    dup["steps"][1]["id"] = "first"
    with pytest.raises(FlowError):
        validate_flow(dup)
    missing_rule = base_flow()
    missing_rule["forbidden"] = [r for r in missing_rule["forbidden"] if r["id"] != "NO_RTL_INTO_UVM"]
    with pytest.raises(FlowError):
        validate_flow(missing_rule)
    bad_policy = base_flow()
    bad_policy["policy"] = {"max_total_tool_calls": 0}
    with pytest.raises(FlowError):
        validate_flow(bad_policy)


def test_resolve_args_types_and_defaults():
    args = resolve_args({"a": "${repo}", "b": "${missing:-dflt}", "c": ["${n}"],
                         "d": "x-${scope}-y", "files": "${rtl_files}"},
                        {"repo": "/r", "n": 3, "scope": "s", "rtl_files": ["f.v"]}, "s1")
    assert args == {"a": "/r", "b": "dflt", "c": [3], "d": "x-s-y", "files": ["f.v"]}
    with pytest.raises(FlowError, match="needs variable 'nope'"):
        resolve_args({"a": "${nope}"}, {}, "s1")


def test_recommended_order_executes_without_llm(tmp_path):
    calls = []
    result = runner.run_flow(write_flow(tmp_path, base_flow()), out_dir=tmp_path / "run",
                             variables={}, registry=stub_registry(calls))
    assert result["status"] == "PASS"
    assert [c[0] for c in calls] == ["stub_a", "stub_b"]
    assert (tmp_path / "run" / "orchestrator_trace.jsonl").exists()
    assert (tmp_path / "run" / "orchestrator_result.json").exists()
    assert not (tmp_path / "run" / "orchestrator_review.json").exists()


def test_llm_revisit_runs_target_with_extra_prompt(tmp_path):
    calls = []
    script = [{"action": "revisit", "target_step": "first",
               "extra_prompt": "Which reset value did the spec state?",
               "reason": "answer was vague"},
              {"action": "continue", "target_step": "", "extra_prompt": "", "reason": "ok"}]
    llm = FakeLLM({"orchestrator_next": lambda payload: script.pop(0) if script
                   else {"action": "continue", "target_step": "",
                         "extra_prompt": "", "reason": "done"}})
    result = runner.run_flow(write_flow(tmp_path, base_flow()), out_dir=tmp_path / "run",
                             variables={}, llm=llm, registry=stub_registry(calls))
    assert result["status"] == "PASS"
    assert [c[0] for c in calls] == ["stub_a", "stub_a", "stub_b"]
    assert calls[1][2] == "Which reset value did the spec state?"
    assert result["overrides_used"] == 1


def test_nagging_decider_hits_budget_and_asks_owner(tmp_path):
    calls = []
    llm = FakeLLM({"orchestrator_next": lambda payload:
                   {"action": "revisit", "target_step": "first",
                    "extra_prompt": "again", "reason": "never satisfied"}})
    flow = base_flow()
    flow["policy"] = {"max_revisits_per_step": 1, "max_overrides": 1,
                      "max_total_tool_calls": 32}
    result = runner.run_flow(write_flow(tmp_path, flow), out_dir=tmp_path / "run",
                             variables={}, llm=llm, registry=stub_registry(calls))
    assert result["status"] == "NEEDS_REVIEW"
    assert "rejected actions" in result["reason"]
    assert [c[0] for c in calls] == ["stub_a", "stub_a", "stub_b"]
    review = json.loads((tmp_path / "run" / "orchestrator_review.json").read_text())
    assert review["approvals_needed"] == ["second"]
    assert "--approve second" in review["resume"]


def test_total_tool_call_budget_bounds_loops(tmp_path):
    calls = []
    flow = base_flow()
    flow["policy"] = {"max_total_tool_calls": 1}
    result = runner.run_flow(write_flow(tmp_path, flow), out_dir=tmp_path / "run",
                             variables={}, registry=stub_registry(calls))
    assert result["status"] == "NEEDS_REVIEW"
    assert "tool-call budget" in result["reason"]
    assert len(calls) == 1


def test_step_timeout_reverts_to_owner(tmp_path):
    calls = []
    flow = base_flow()
    flow["steps"] = [{"id": "slow", "tool": "stub_a", "agent": "dv", "args": {},
                      "timeout_s": 1, "max_attempts": 1}]
    specs = stub_registry(calls, {"stub_a": {"sleep": 2}})
    started = time.monotonic()
    result = runner.run_flow(write_flow(tmp_path, flow), out_dir=tmp_path / "run",
                             variables={}, registry=specs)
    assert time.monotonic() - started < 15
    assert result["status"] == "NEEDS_REVIEW"
    assert "TIMEOUT" in result["reason"] and "exceeded" in result["reason"]
    assert result["steps"][0]["status"] == "TIMEOUT"
    assert len(calls) == 1


def test_review_gate_blocks_until_approved(tmp_path):
    flow = base_flow()
    flow["steps"][1]["review_gate"] = True
    flow_path = write_flow(tmp_path, flow)
    calls = []
    gated = runner.run_flow(flow_path, out_dir=tmp_path / "run", variables={},
                            registry=stub_registry(calls))
    assert gated["status"] == "NEEDS_REVIEW"
    assert [c[0] for c in calls] == ["stub_a"]
    calls.clear()
    approved = runner.run_flow(flow_path, out_dir=tmp_path / "run2", variables={},
                               approvals=["second"], registry=stub_registry(calls))
    assert approved["status"] == "PASS"
    assert [c[0] for c in calls] == ["stub_a", "stub_b"]


def test_forbidden_rtl_arg_into_uvm_is_blocked(tmp_path):
    flow = base_flow()
    flow["steps"] = [{"id": "uvm", "tool": "uvm_build", "agent": "dv",
                      "args": {"interface": "if.json", "out": "${out}/uvm",
                               "rtl_graph": "g.json"}}]
    out = tmp_path / "run"
    result = runner.run_flow(write_flow(tmp_path, flow), out_dir=out,
                             variables={}, registry=stub_registry([]))
    assert result["status"] == "NEEDS_REVIEW"
    assert "NO_RTL_INTO_UVM" in result["reason"]
    assert result["violations"]


def test_forbidden_rtl_behavior_file_into_uvm_is_blocked(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    graph_file = str((out / "rtl_graph.json").resolve())
    violations = pre_tool_check(tool="uvm_build",
                                args={"interface": graph_file, "out": str(out)},
                                extra_prompt="", out_dir=out,
                                rtl_behavior_files={graph_file})
    assert any("NO_RTL_INTO_UVM" in v for v in violations)
    interface_file = str((out / "interface_definition.json").resolve())
    ok = pre_tool_check(tool="uvm_build",
                        args={"interface": interface_file, "out": str(out)},
                        extra_prompt="", out_dir=out,
                        rtl_behavior_files={graph_file})
    assert ok == []


def test_spec_step_with_rtl_input_is_blocked(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    violations = pre_tool_check(tool="dv_interfaces", args={"rtl_graph": "g.json"},
                                extra_prompt="", out_dir=out, rtl_behavior_files=set())
    assert any("NO_SPEC_FLOW_CONTAMINATION" in v for v in violations)


def test_unknown_forbidden_rule_fails_closed(tmp_path):
    flow = base_flow()
    flow["forbidden"].append({"id": "NO_TELEPATHY", "title": "made up"})
    result = runner.run_flow(write_flow(tmp_path, flow), out_dir=tmp_path / "run",
                             variables={}, registry=stub_registry([]))
    assert result["status"] == "BLOCKED"
    assert "NO_TELEPATHY" in result["reason"]


def test_unknown_tool_fails_closed(tmp_path):
    flow = base_flow()
    flow["steps"][0]["tool"] = "teleporter"
    result = runner.run_flow(write_flow(tmp_path, flow), out_dir=tmp_path / "run",
                             variables={}, registry=stub_registry([]))
    assert result["status"] == "BLOCKED"
    assert "teleporter" in result["reason"]


def test_post_testplan_check_requires_unapproved_observations(tmp_path):
    doc = tmp_path / "testplan_doc.json"
    doc.write_text(json.dumps({"sections": [
        {"generator": "rtl_observations", "entries": [
            {"id": "RTLOBS-1", "review_status": "NEEDS_REVIEW", "provenance": "INFERRED"}]}]}))
    assert post_testplan_check(doc_path=doc, rtl_used=True) == []
    doc.write_text(json.dumps({"sections": [
        {"generator": "rtl_observations", "entries": [
            {"id": "RTLOBS-1", "review_status": "APPROVED", "provenance": "DOCUMENTED"}]}]}))
    violations = post_testplan_check(doc_path=doc, rtl_used=True)
    assert len(violations) == 2
    assert post_testplan_check(doc_path=doc, rtl_used=False) == []


def test_invalid_decider_proposal_is_ignored(tmp_path):
    calls = []
    llm = FakeLLM({"orchestrator_next": lambda payload:
                   {"action": "revisit", "target_step": "nope",
                    "extra_prompt": "", "reason": "invented"}})
    result = runner.run_flow(write_flow(tmp_path, base_flow()), out_dir=tmp_path / "run",
                             variables={}, llm=llm, registry=stub_registry(calls))
    assert result["status"] == "PASS"
    assert [c[0] for c in calls] == ["stub_a", "stub_b"]
    assert result["invalid_decider_proposals"] >= 1
    assert result["overrides_used"] == 0


def test_decider_stop_reverts_to_owner(tmp_path):
    llm = FakeLLM({"orchestrator_next": lambda payload:
                   {"action": "stop", "target_step": "", "extra_prompt": "",
                    "reason": "something smells"}})
    result = runner.run_flow(write_flow(tmp_path, base_flow()), out_dir=tmp_path / "run",
                             variables={}, llm=llm, registry=stub_registry([]))
    assert result["status"] == "NEEDS_REVIEW"
    assert "something smells" in result["reason"]


def test_cli_validate_and_status(tmp_path, capsys):
    repo_root = Path(__file__).resolve().parents[1]
    default = repo_root / "src/orchestrator_agent/flows/default_flow.json"
    assert cli_main(["validate", "--flow", str(default)]) == 0
    capsys.readouterr()
    flow_path = write_flow(tmp_path, base_flow())
    out = tmp_path / "run"
    result = runner.run_flow(flow_path, out_dir=out, variables={},
                             registry=stub_registry([]))
    assert result["status"] == "PASS"
    assert cli_main(["status", "--out", str(out)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["status"] == "PASS"


def test_cli_run_reports_needs_review_exit_code(tmp_path):
    flow = base_flow()
    flow["steps"] = [{"id": "gated", "tool": "dv_ingest", "agent": "dv",
                      "review_gate": True, "args": {}}]
    flow_path = write_flow(tmp_path, flow)
    code = cli_main(["run", "--flow", str(flow_path), "--out", str(tmp_path / "run"),
                     "--llm", "off"])
    assert code == 3


def test_real_offline_tools_through_runner(tmp_path, spec_repo):
    rtl = tmp_path / "block.sv"
    rtl.write_text("module block(input logic clk, input logic [7:0] data, "
                   "output logic irq);\nendmodule\n")
    flow = base_flow()
    flow["steps"] = [
        {"id": "ingest", "tool": "dv_ingest", "agent": "dv",
         "args": {"repo": "${repo}", "out": "${out}/dv"}},
        {"id": "ports", "tool": "rtl_extract", "agent": "rtl",
         "args": {"files": "${rtl_files}", "top": "block", "out": "${out}/rtl",
                 "build": True}},
    ]
    out = tmp_path / "run"
    result = runner.run_flow(write_flow(tmp_path, flow), out_dir=out,
                             variables={"repo": str(spec_repo),
                                        "rtl_files": [str(rtl)]})
    assert result["status"] == "PASS"
    assert (out / "dv" / "manifest.json").exists()
    assert (out / "rtl" / "interface_definition.json").exists()


def test_default_flow_validates():
    from orchestrator_agent.tools import REGISTRY
    repo_root = Path(__file__).resolve().parents[1]
    flow = load_flow(repo_root / "src/orchestrator_agent/flows/default_flow.json")
    assert {s["tool"] for s in flow["steps"]} <= set(REGISTRY)
    assert flow["steps"][-1]["review_gate"] is True
