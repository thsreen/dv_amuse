"""Offline tests for the DV/RTL orchestrator: order, overrides, budgets, guards."""
import json
import time
from pathlib import Path

import pytest

from dv_agent.core.llm import FakeLLM
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


def test_llm_revisit_runs_target_with_extra_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("DV_AGENT_MODE", "graph")
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


def test_nagging_decider_hits_budget_and_asks_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("DV_AGENT_MODE", "graph")
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


@pytest.mark.parametrize("tool", ["dv_build_graph", "dv_testplan"])
def test_checkpointed_model_stage_never_starts_timeout_worker(tmp_path, monkeypatch, tool):
    calls = []
    def invoke(args, ctx):
        calls.append(tool)
        return dict(status="FAIL", summary="bounded API recovery exhausted", files=[])
    def forbidden_timeout(*args):
        pytest.fail("checkpointed model stages must not leave a background writer")
    monkeypatch.setattr(runner, "call_with_timeout", forbidden_timeout)
    flow = base_flow(steps=[dict(id="model", tool=tool, agent="dv", args={}, max_attempts=1)])
    result = runner.run_flow(write_flow(tmp_path, flow), out_dir=tmp_path / "run",
                             variables={}, registry={tool: ToolSpec("dv", SPEC, False, invoke)})
    assert calls == [tool]
    assert result["status"] == "NEEDS_REVIEW"


def test_basic_mode_uses_150_second_model_timeout(monkeypatch):
    from orchestrator_agent.cli import _models_for
    monkeypatch.setenv('MODEL_API_KEY','offline-fixture')
    monkeypatch.setenv('DV_AGENT_MODE','basic')
    monkeypatch.delenv('META_REQUEST_TIMEOUT_SECONDS',raising=False)
    llm,embedder=_models_for('on')
    assert llm.timeout==150 and llm.max_attempts==2 and embedder is None


def test_model_interruption_records_final_result_and_progress_without_dashboard(tmp_path):
    from dv_agent.core.progress import emit
    def interrupted(args,ctx):
        emit('request diagnostic persisted without dashboard')
        raise KeyboardInterrupt()
    flow=base_flow(steps=[dict(id='model',tool='dv_testplan',agent='dv',args={},max_attempts=1)])
    result=runner.run_flow(write_flow(tmp_path,flow),out_dir=tmp_path/'run',variables={},
                          registry={'dv_testplan':ToolSpec('dv',SPEC,False,interrupted)})
    assert result['status']=='NEEDS_REVIEW' and result['steps'][0]['status']=='INTERRUPTED'
    saved=json.loads((tmp_path/'run/orchestrator_result.json').read_text())
    assert 'interrupted' in saved['reason']
    records=[json.loads(line) for line in (tmp_path/'run/orchestrator_trace.jsonl').read_text().splitlines()]
    assert any(r['event']=='task_progress' for r in records)
    assert any(r['event']=='tool_interrupted' and r['elapsed_s']>=0 for r in records)
    assert records[-1]['event']=='run_finish'


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


def test_invalid_decider_proposal_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("DV_AGENT_MODE", "graph")
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


def test_decider_stop_reverts_to_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("DV_AGENT_MODE", "graph")
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


def scripted(lines):
    it = iter(lines)

    def read(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return read


def test_repl_quits_and_handles_eof():
    from orchestrator_agent.repl import repl
    assert repl(input_fn=scripted(["/quit"]), output_fn=lambda line: None) == 0
    assert repl(input_fn=scripted([]), output_fn=lambda line: None) == 0


def _prompt_repo(tmp_path):
    repo = tmp_path / "sample_design"
    (repo / "doc").mkdir(parents=True)
    (repo / "rtl").mkdir()
    (repo / "doc" / "spec.txt").write_text("A small documented design.")
    (repo / "rtl" / "chip_top.sv").write_text(
        "module chip_top(input clk, input reset, input data, output reg q);\n"
        "always @(posedge clk or posedge reset) if (reset) q <= 0; else q <= data;\nendmodule\n")
    return repo


def test_repl_prompt_previews_english_steps_and_only_four_commands(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    repo = _prompt_repo(tmp_path)
    monkeypatch.setattr(terminal, "_default_out", lambda: tmp_path / "run")
    shown = []
    code = terminal.repl(input_fn=scripted([f"Plan tests for {repo}", "/unknown"]),
                         output_fn=shown.append, llm_mode="off")
    assert code == 0
    text = "\n".join(shown)
    assert "--- testplan preview ---" in text
    assert "Read specification files" in text and "Recover registers" in text
    assert "RTL top: chip_top" in text and "ready: yes" in text
    assert terminal.HELP == "Commands: /plan  /code  /run  /regress  /fresh  (Ctrl-D to leave)"


def test_repl_four_commands_run_in_order_without_manual_variables(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    repo = _prompt_repo(tmp_path)
    out = tmp_path / "run"
    monkeypatch.setattr(terminal, "_default_out", lambda: out)
    calls = []
    def fake_flow(flow_path, *, out_dir, variables, **kwargs):
        calls.append(("plan", variables))
        (out_dir / "dv").mkdir(parents=True)
        (out_dir / "dv" / "testplan_doc.json").write_text("{}")
        return dict(status="PASS", reason="done")
    def fake_code(out_dir, variables, **kwargs):
        calls.append(("code", variables))
        return dict(code_dir=str(out_dir / "code"), policy=dict(kept=1, skipped=2),
                    tests=[dict(name="basic_smoke")])
    def fake_tests(out_dir, *, regress):
        calls.append(("regress" if regress else "run", out_dir))
        return dict(status="PASS", tests=[dict(name="basic_smoke", status="PASS", reason="exit 0")])
    monkeypatch.setattr(terminal, "run_flow", fake_flow)
    monkeypatch.setattr(terminal, "build_code", fake_code)
    monkeypatch.setattr(terminal, "run_tests", fake_tests)
    shown = []
    assert terminal.repl(input_fn=scripted([f"Verify {repo}", "/plan", "/code", "/run", "/regress"]),
                         output_fn=shown.append, llm=object()) == 0
    assert [c[0] for c in calls] == ["plan", "code", "run", "regress"]
    assert calls[0][1]["rtl_files"] == [str(repo / "rtl" / "chip_top.sv")]
    assert json.loads((out / "orchestrator_ask.json").read_text())["requirement"] == f"Verify {repo}"


def test_repl_code_generates_plan_first(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    repo = _prompt_repo(tmp_path)
    out = tmp_path / "run"
    monkeypatch.setattr(terminal, "_default_out", lambda: out)
    called = []
    def fake_flow(flow_path, *, out_dir, variables, **kwargs):
        called.append("plan")
        (out_dir / "dv").mkdir(parents=True)
        (out_dir / "dv" / "testplan_doc.json").write_text("{}")
        return dict(status="PASS", reason="done")
    monkeypatch.setattr(terminal, "run_flow", fake_flow)
    monkeypatch.setattr(terminal, "build_code", lambda out_dir, variables, **kwargs: called.append("code") or
                        dict(code_dir="code", policy=dict(kept=0, skipped=0), tests=[dict(name="basic_smoke")]))
    assert terminal.repl(input_fn=scripted([f"Verify {repo}", "/code"]),
                         output_fn=lambda text: None, llm=object()) == 0
    assert called == ["plan", "code"]


def test_repl_opens_local_viewer_after_report_is_written(tmp_path, monkeypatch):
    import threading
    from orchestrator_agent import repl as terminal
    repo = _prompt_repo(tmp_path)
    out = tmp_path / "run"
    monkeypatch.setattr(terminal, "_default_out", lambda: out)
    closed = threading.Event()
    class FakeServer:
        server_port = 9345
        def serve_forever(self):
            closed.wait(2)
        def shutdown(self):
            closed.set()
        def server_close(self):
            closed.set()
    roots = []
    monkeypatch.setattr(terminal, "create_report_server", lambda root, port: roots.append((root, port)) or FakeServer())
    def fake_flow(flow_path, *, out_dir, variables, **kwargs):
        report = out_dir / "dv"
        report.mkdir(parents=True)
        (report / "testplan_doc.json").write_text("{}")
        (report / "testplan_doc.md").write_text("# Plan\n")
        (report / "testplan_doc.html").write_text("<h1>Plan</h1>")
        return dict(status="PASS", reason="done")
    monkeypatch.setattr(terminal, "run_flow", fake_flow)
    shown = []
    assert terminal.repl(input_fn=scripted([f"Verify {repo}", "/plan"]),
                         output_fn=shown.append, llm=object()) == 0
    assert roots == [(out, 0)] and closed.is_set()
    text = "\n".join(shown)
    assert "For the polished testplan, open: http://127.0.0.1:9345/?plan=dv" in text
    assert "HTML file:" in text and "Editable Markdown:" in text


def test_entry_point_starts_repl(monkeypatch):
    from orchestrator_agent import cli
    seen = []
    monkeypatch.setattr(cli, "load_env_file", lambda path: None)
    monkeypatch.setattr("orchestrator_agent.repl.repl", lambda **kwargs: seen.append(kwargs) or 0)
    assert cli_main([]) == 0
    assert seen and seen[0]["llm_mode"] is None


def test_runner_event_sink_receives_lifecycle(tmp_path):
    events = []
    result = runner.run_flow(write_flow(tmp_path, base_flow()), out_dir=tmp_path / "run",
                             variables={}, registry=stub_registry([]), event_sink=events.append)
    assert result["status"] == "PASS"
    kinds = [e["event"] for e in events]
    assert kinds[0] == "run_start" and kinds[-1] == "run_finish"
    assert kinds.count("tool_start") == 2 and kinds.count("tool_done") == 2


def test_runner_forwards_dv_progress_and_substep_events(tmp_path):
    from dv_agent.core.progress import emit, emit_event
    calls, events = [], []
    registry = stub_registry(calls)
    def stage(args, ctx):
        emit("extracting requirements")
        emit_event("substep_start", id="registers", label="Recover registers")
        emit_event("substep_done", id="registers", status="PASS")
        return dict(status="PASS", summary="done", files=[])
    registry["stub_a"] = ToolSpec("dv", SPEC, False, stage)
    result = runner.run_flow(write_flow(tmp_path, base_flow()), out_dir=tmp_path / "run",
                             variables={}, registry=registry, event_sink=events.append)
    assert result["status"] == "PASS"
    assert [(e["event"], e.get("id")) for e in events if e["event"].startswith("substep_")] == [
        ("substep_start", "registers"), ("substep_done", "registers")]
    assert any(e["event"] == "task_progress" and "requirements" in e["message"] for e in events)


def test_dashboard_frame_lists_steps_and_tool_call(tmp_path):
    from orchestrator_agent.tui import Dashboard
    flow = validate_flow(base_flow())
    shown = []
    dash = Dashboard(tmp_path, shown.append, flow=flow, title="verify it", ansi=True)
    dash.handle({"event": "run_start", "steps": ["first", "second"]})
    dash.handle({"event": "tool_start", "step": "first", "tool": "stub_a",
                 "attempt": 1, "revisit": 0, "extra_prompt": "sharper?"})
    frame = shown[-1]
    assert "first" in frame and "second" in frame and "stub_a" in frame
    assert "sharper?" in frame and "tokens in 0 out 0" in frame
    assert "calls 1/32" in frame and "verify it" in frame
    dash.handle({"event": "tool_done", "step": "first", "status": "PASS", "summary": "ok"})
    dash.handle({"event": "run_finish", "status": "PASS", "reason": "done"})
    assert "PASS" in shown[-1] and "done" in shown[-1]


def test_dashboard_plain_mode_without_ansi(tmp_path):
    from orchestrator_agent.tui import Dashboard
    shown = []
    dash = Dashboard(tmp_path, shown.append, flow=validate_flow(base_flow()), ansi=False)
    dash.handle({"event": "tool_start", "step": "first", "tool": "stub_a",
                 "attempt": 1, "revisit": 0, "extra_prompt": ""})
    dash.handle({"event": "tool_done", "step": "first", "status": "PASS", "summary": "ok"})
    assert shown == ["[run] first: stub_a", "[PASS] first: ok"]


def test_dashboard_expands_testplan_and_middle_progress(tmp_path):
    from orchestrator_agent.tui import Dashboard
    flow = load_flow(Path(__file__).resolve().parents[1] /
                     "src/orchestrator_agent/flows/testplan_flow.json")
    shown = []
    dash = Dashboard(tmp_path, shown.append, flow=flow, title="UART plan", ansi=True)
    dash.started -= 65
    dash.handle({"event": "run_start", "steps": [s["id"] for s in flow["steps"]]})
    dash.handle({"event": "tool_start", "step": "testplan", "tool": "dv_testplan", "attempt": 1})
    dash.handle({"event": "substep_start", "step": "testplan", "id": "registers",
                 "label": "Recover registers and configurable controls"})
    dash.handle({"event": "task_progress", "step": "testplan", "message": "registers batch [2/3]"})
    frame = shown[-1]
    assert "progress" in frame and "current task" in frame
    assert "Recover registers" in frame and "registers batch [2/3]" in frame
    assert "task progress" in frame and "2/3" in frame
    assert "started" in frame and "elapsed" in frame and "00:00:00" in frame
    assert "Configurations" in frame and "Observations from RTL" in frame
    frames_before_completion = len(shown)
    dash.handle({"event": "substep_done", "step": "testplan", "id": "registers", "status": "PASS"})
    assert len(shown) == frames_before_completion + 1
    assert "00:01:05" in shown[-1]
    assert dash.substatus["registers"] == "PASS"


def test_repl_plan_requires_repository_and_model(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    monkeypatch.setattr(terminal, "_default_out", lambda: tmp_path / "run")
    shown = []
    assert terminal.repl(input_fn=scripted(["Make a plan", "/plan"]),
                         output_fn=shown.append, llm_mode="off") == 0
    assert "Name a local repository" in "\n".join(shown)
    assert not (tmp_path / "run").exists()


def test_scan_tokens_counts_usage_and_ignores_deep_trees(tmp_path):
    from orchestrator_agent.tui import scan_tokens
    near = tmp_path / "dv" / "trace.jsonl"
    near.parent.mkdir()
    near.write_text('{"usage": {"input": 10, "output": 3}}\n{"name": "x"}\n')
    deep = tmp_path / "a" / "b" / "c" / "d" / "trace.jsonl"
    deep.parent.mkdir(parents=True)
    deep.write_text('{"usage": {"input": 9999, "output": 9999}}\n')
    assert scan_tokens(tmp_path) == {"calls": 1, "input": 10, "output": 3, "cached_input": 0}


def _seed_run(out: Path, *, status="NEEDS_REVIEW", reason="step 'testplan' ended FAIL: boom"):
    out.mkdir(parents=True, exist_ok=True)
    (out / "orchestrator_result.json").write_text(json.dumps(
        dict(status=status, reason=reason,
             steps=[dict(id="spec_ingest", tool="dv_ingest", status="PASS",
                         attempts=1, revisits=0, summary="ingested 3 chunks"),
                    dict(id="testplan", tool="dv_testplan", status="FAIL",
                         attempts=2, revisits=0, summary="boom")])), encoding="utf-8")
    (out / "orchestrator_review.json").write_text(json.dumps(
        dict(status="NEEDS_REVIEW", reason=reason, question="Fix the cause, then approve.",
             pending_step="testplan", violations=["testplan: boom"])), encoding="utf-8")


def test_repl_fresh_command_resets_session_to_new_out_dir(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    repo = _prompt_repo(tmp_path)
    dirs = iter([tmp_path / "run1", tmp_path / "run2"])
    monkeypatch.setattr(terminal, "_default_out", lambda: next(dirs))
    shown = []
    assert terminal.repl(input_fn=scripted([f"Verify {repo}", "/fresh", "/plan"]),
                         output_fn=shown.append, llm_mode="off") == 0
    text = "\n".join(shown)
    assert "Fresh session" in text and str(tmp_path / "run2") in text
    assert "Name a local repository" in text  # scan/variables were reset


def test_repl_fresh_phrase_without_command(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    repo = _prompt_repo(tmp_path)
    dirs = iter([tmp_path / "run1", tmp_path / "run2"])
    monkeypatch.setattr(terminal, "_default_out", lambda: next(dirs))
    shown = []
    assert terminal.repl(input_fn=scripted([f"Verify {repo}", "start fresh"]),
                         output_fn=shown.append, llm_mode="off") == 0
    assert "Fresh session" in "\n".join(shown)


def test_repl_explain_summarizes_review(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    out = tmp_path / "run"
    _seed_run(out)
    monkeypatch.setattr(terminal, "_default_out", lambda: out)
    shown = []
    assert terminal.repl(input_fn=scripted(["why did it fail?"]),
                         output_fn=shown.append, llm_mode="off") == 0
    text = "\n".join(shown)
    assert "boom" in text and "NEEDS_REVIEW" in text and "testplan" in text


def test_repl_show_artifact_summarizes_or_points_to_plan(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    out = tmp_path / "run"
    (out / "dv").mkdir(parents=True)
    (out / "dv" / "interfaces.json").write_text(json.dumps(
        dict(groups=[dict(name="bus", signals=[dict(name="clk"), dict(name="rst")])])), encoding="utf-8")
    monkeypatch.setattr(terminal, "_default_out", lambda: out)
    shown = []
    assert terminal.repl(input_fn=scripted(["show interfaces", "show registers"]),
                         output_fn=shown.append, llm_mode="off") == 0
    text = "\n".join(shown)
    assert "bus" in text and "clk" in text
    assert "not found" in text and "/plan" in text


def test_repl_validate_flow_reports_pass_or_problems(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    repo_root = Path(__file__).resolve().parents[1]
    good = repo_root / "src/orchestrator_agent/flows/default_flow.json"
    bad = tmp_path / "bad_flow.json"
    bad.write_text(json.dumps(base_flow(steps=[dict(id="x", tool="nope", agent="dv", args={})])),
                   encoding="utf-8")
    monkeypatch.setattr(terminal, "_default_out", lambda: tmp_path / "run")
    shown = []
    assert terminal.repl(input_fn=scripted([f"validate {good}", f"validate {bad}", "validate"]),
                         output_fn=shown.append, llm_mode="off") == 0
    text = "\n".join(shown)
    assert "PASS" in text and "unknown tool 'nope'" in text and "usage" in text.lower()


def test_repl_status_reports_run_or_missing_result(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    out = tmp_path / "run"
    _seed_run(out)
    monkeypatch.setattr(terminal, "_default_out", lambda: out)
    shown = []
    assert terminal.repl(input_fn=scripted(["status"]), output_fn=shown.append, llm_mode="off") == 0
    assert "boom" in "\n".join(shown)
    shown.clear()
    assert terminal.repl(input_fn=scripted([f"status of {tmp_path / 'empty'}"]),
                         output_fn=shown.append, llm_mode="off") == 0
    assert "no orchestrator result" in "\n".join(shown)


def test_repl_rerun_executes_guarded_tool(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    from orchestrator_agent.tools import SPEC, ToolSpec
    repo = _prompt_repo(tmp_path)
    out = tmp_path / "run"
    monkeypatch.setattr(terminal, "_default_out", lambda: out)
    calls = []
    def run_registers(args, ctx, mode="graph"):
        calls.append(dict(args))
        return dict(status="PASS", summary="registers ok", files=[])
    registry = {"dv_registers": ToolSpec("dv", SPEC, True, run_registers)}
    shown = []
    assert terminal.repl(input_fn=scripted([f"Verify {repo}", "rerun registers", "rerun frobnicate"]),
                         output_fn=shown.append, llm=object(), registry=registry) == 0
    assert len(calls) == 1 and calls[0]["out"] == str(out / "dv")
    text = "\n".join(shown)
    assert "registers ok" in text and "supported reruns" in text


def test_run_single_tool_enforces_guards(tmp_path):
    from orchestrator_agent.runner import run_single_tool
    from orchestrator_agent.tools import SPEC, ToolSpec
    out = tmp_path / "run"
    calls = []
    def make(name):
        def stub(args, ctx):
            calls.append(name)
            return dict(status="PASS", summary="ok", files=[])
        return stub
    registry = {name: ToolSpec("dv", SPEC, False, make(name))
                for name in ("stub_a", "dv_ingest", "uvm_build")}
    refused = run_single_tool("nope", {}, out_dir=out, registry=registry)
    assert refused["status"] == "BLOCKED" and "NO_NEW_TOOLS" in refused["summary"]
    escaped = run_single_tool("stub_a", {"out": str(tmp_path / "evil")}, out_dir=out, registry=registry)
    assert escaped["status"] == "BLOCKED" and "NO_DESIGN_MUTATION" in escaped["summary"]
    dirty = run_single_tool("dv_ingest", {"out": str(out), "rtl_graph": "x"}, out_dir=out, registry=registry)
    assert dirty["status"] == "BLOCKED" and "NO_SPEC_FLOW_CONTAMINATION" in dirty["summary"]
    leak = run_single_tool("uvm_build", {"out": str(out), "rtl_excerpts": ["x"]}, out_dir=out,
                           registry=registry)
    assert leak["status"] == "BLOCKED" and "NO_RTL_INTO_UVM" in leak["summary"]
    assert calls == []
    ok = run_single_tool("stub_a", {"out": str(out)}, out_dir=out, registry=registry)
    assert ok["status"] == "PASS" and calls == ["stub_a"]
    trace = (out / "orchestrator_trace.jsonl").read_text(encoding="utf-8")
    assert "single_tool_start" in trace and "guard_block" in trace


def test_reset_out_dir_clears_run_state_and_refuses_foreign_dirs(tmp_path):
    from orchestrator_agent.runner import reset_out_dir
    fresh = tmp_path / "new"
    assert reset_out_dir(fresh) == [] and fresh.is_dir()
    run = tmp_path / "run"
    (run / "dv" / "llm_cache").mkdir(parents=True)
    (run / "dv" / "graph.json").write_text("{}")
    (run / "orchestrator_result.json").write_text("{}")
    cleared = reset_out_dir(run)
    assert run.is_dir() and list(run.iterdir()) == []
    assert sorted(cleared) == ["dv", "orchestrator_result.json"]
    foreign = tmp_path / "repo"
    (foreign / "src").mkdir(parents=True)
    (foreign / "top.sv").write_text("module top; endmodule")
    with pytest.raises(ValueError, match="refusing to clear"):
        reset_out_dir(foreign)
    assert (foreign / "top.sv").is_file()


def test_cli_run_fresh_clears_out_dir_and_forces(tmp_path, monkeypatch, capsys):
    import orchestrator_agent.runner as runner_mod
    out = tmp_path / "run"
    (out / "dv" / "llm_cache").mkdir(parents=True)
    (out / "orchestrator_review.json").write_text("{}")
    seen = {}
    def fake_flow(flow_path, *, out_dir, variables, force=False, **kwargs):
        seen.update(force=force, out=str(out_dir))
        return dict(status="PASS", reason="fresh ok")
    monkeypatch.setattr(runner_mod, "run_flow", fake_flow)
    code = cli_main(["run", "--flow", str(write_flow(tmp_path, base_flow())),
                     "--out", str(out), "--fresh", "--llm", "off"])
    assert code == 0 and seen == {"force": True, "out": str(out)}
    assert list(out.iterdir()) == []
    assert "fresh" in capsys.readouterr().err.lower()


def test_interpret_routes_intents_and_ignores_repo_lines():
    from orchestrator_agent.assist import interpret
    assert interpret("start fresh")["intent"] == "fresh"
    assert interpret("be fresh.")["intent"] == "fresh"
    assert interpret("why did the plan fail")["intent"] == "explain"
    assert interpret("what are the registers?") == dict(intent="show", target="registers")
    assert interpret("rerun the registers step") == dict(intent="rerun", target="registers")
    assert interpret("run registers again") == dict(intent="rerun", target="registers")
    assert interpret("validate /tmp/flow.json") == dict(intent="validate", path="/tmp/flow.json")
    assert interpret("status") == dict(intent="status", path="")
    # Repository descriptions and paths fall through to the scan path.
    assert interpret("Verify /tmp/chip") is None
    assert interpret("Plan tests for /tmp/chip") is None
    assert interpret("Make a plan") is None
    assert interpret("Verify /tmp/run") is None
    assert interpret("refresh the plan") is None
    assert interpret("/fresh") is None


def test_repl_fresh_twice_same_second_yields_distinct_dirs(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    same = tmp_path / "run"
    monkeypatch.setattr(terminal, "_default_out", lambda: same)
    shown = []
    assert terminal.repl(input_fn=scripted(["start fresh", "start fresh"]),
                         output_fn=shown.append, llm_mode="off") == 0
    text = "\n".join(shown)
    assert f"Fresh session in {same}-2" in text
    assert f"Fresh session in {same}-3" in text


def test_timed_out_tool_is_cancelled_and_starts_no_more_model_calls():
    import threading

    from dv_agent.core import cancel
    from dv_agent.core.llm import LLMError, MetaClient
    from orchestrator_agent.runner import call_with_timeout

    started, release, outcome = threading.Event(), threading.Event(), {}

    class Boom:  # any SDK call after cancellation is a bug
        class responses:
            @staticmethod
            def create(**_):
                outcome["called"] = True
                raise AssertionError("model call after cancellation")

    def tool():
        started.set()
        release.wait(5)
        try:
            MetaClient(client=Boom, api_key="k").structured(name="n", instructions="i", payload={}, schema={})
        except LLMError as exc:
            outcome["error"] = exc.kind
        finally:
            outcome["done"] = True

    assert call_with_timeout(tool, 0.2) == ("timeout", None)
    assert started.is_set() and not cancel.is_cancelled()  # the caller's own context is unaffected
    release.set()
    for _ in range(100):
        if outcome.get("done"):
            break
        threading.Event().wait(0.02)
    assert outcome == {"error": "cancelled", "done": True}


def test_cancellation_reaches_worker_pool_threads():
    import concurrent.futures
    import threading

    from dv_agent.core import cancel

    token = threading.Event()

    def work():
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(cancel.bind(lambda _: cancel.is_cancelled()), range(3)))

    runner = cancel.in_scope(token, work)
    assert runner() == [False, False, False]
    token.set()
    assert runner() == [True, True, True]


def test_model_stage_is_stopped_at_the_global_deadline_instead_of_running_on(tmp_path):
    from dv_agent.core import cancel
    seen = {}

    def long_stage(args, ctx):
        deadline = time.monotonic() + 10
        while not cancel.is_cancelled() and time.monotonic() < deadline:
            time.sleep(0.05)
        seen["cancelled"] = cancel.is_cancelled()
        return dict(status="FAIL", summary="stopped at the deadline", files=[])

    flow = base_flow(policy={"global_timeout_s": 1},
                     steps=[dict(id="plan", tool="dv_testplan", agent="dv", args={}, max_attempts=1),
                            dict(id="after", tool="stub_b", agent="rtl", args={})])
    calls = []
    registry = dict(stub_registry(calls), dv_testplan=ToolSpec("dv", SPEC, False, long_stage))
    started = time.monotonic()
    result = runner.run_flow(write_flow(tmp_path, flow), out_dir=tmp_path / "run", variables={}, registry=registry)
    assert time.monotonic() - started < 8 and seen == {"cancelled": True}
    assert result["status"] == "NEEDS_REVIEW" and not calls  # the next step was not started
    events = [json.loads(line) for line in (tmp_path / "run/orchestrator_trace.jsonl").read_text().splitlines()]
    assert any(e["event"] == "budget_exhausted" and e.get("detail") for e in events)
