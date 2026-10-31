import json
import subprocess

from orchestrator_agent.actions import build_code, documented_plan, run_tests


def _inputs(tmp_path):
    out = tmp_path / "run"
    (out / "dv").mkdir(parents=True)
    (out / "rtl").mkdir()
    source = tmp_path / "chip_top.sv"
    source.write_text("module chip_top(input clk, input reset, input data, output reg q);\n"
                      "always @(posedge clk or posedge reset) if (reset) q <= 0; else q <= data;\n"
                      "endmodule\n")
    plan = {"sections": [
        {"id": "strategy", "strategy": {"agents": [], "scoreboards": [], "environment": "proposed"}},
        {"id": "stimulus", "entries": [
            {"text": "documented", "provenance": "DOCUMENTED", "cited_req_ids": ["REQ-1"]},
            {"text": "inferred", "provenance": "INFERRED", "cited_req_ids": ["REQ-1"]},
            {"text": "uncited", "provenance": "DOCUMENTED", "cited_req_ids": []}]},
        {"id": "configurations", "configurations": []}]}
    plan['interfaces'] = dict(status='PASS', signals=[
        dict(name=name, direction=direction, width=1, chunk_id='CH-spec')
        for name, direction in [('clk', 'input'), ('reset', 'input'), ('data', 'input'), ('q', 'output')]])
    (out / "dv" / "testplan_doc.json").write_text(json.dumps(plan))
    definition = {"sources": ["chip_top.sv"], "direction_reference": "DUT", "parameters": [],
                  "ports": [{"direction": "input", "width": 1, "name": "clk"},
                            {"direction": "input", "width": 1, "name": "reset"},
                            {"direction": "input", "width": 1, "name": "data"},
                            {"direction": "output", "width": 1, "name": "q"}]}
    (out / "rtl" / "interface_definition.json").write_text(json.dumps(definition))
    return out, source, plan


def test_documented_code_excludes_inferences_and_builds_basic_test(tmp_path):
    out, source, plan = _inputs(tmp_path)
    filtered, policy = documented_plan(plan)
    assert [e["text"] for e in filtered["sections"][1]["entries"]] == ["documented"]
    assert policy["kept"] == 1 and policy["skipped"] == 2
    result = build_code(out, dict(rtl_top="chip_top", rtl_graph_files=[str(source)]))
    assert result["policy"] == policy and result["tests"][0]["name"] == "basic_smoke"
    code = (out / "code" / result["code_dir"].split("/")[-1])
    assert "BASIC_SMOKE_PASS" in (code / "orchestrator_smoke_tb.sv").read_text()
    assert "bit enable_base_sequence = 0;" in (code / "uvm" / "chip_top_cfg.svh").read_text()
    assert build_code(out, dict(rtl_top="chip_top", rtl_graph_files=[str(source)]))["reused"] is True


def test_run_and_regress_execute_only_manifest_tests(tmp_path, monkeypatch):
    out, source, _ = _inputs(tmp_path)
    build_code(out, dict(rtl_top="chip_top", rtl_graph_files=[str(source)]))
    binary = tmp_path / "xezim"
    binary.write_text("stub")
    monkeypatch.setenv("XEZIM_BIN", str(binary))
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "BASIC_SMOKE_PASS\n", "")
    monkeypatch.setattr("orchestrator_agent.actions.subprocess.run", fake_run)
    one = run_tests(out)
    all_tests = run_tests(out, regress=True)
    assert one["status"] == all_tests["status"] == "PASS"
    assert len(calls) == 2 and calls[0][-1].endswith("orchestrator_smoke_tb.sv")
    assert (out / "simulation" / "basic_smoke.log").read_text() == "BASIC_SMOKE_PASS\n"


def test_testplan_step_reports_incomplete_sections(tmp_path, monkeypatch):
    from orchestrator_agent.tools import StepContext, run_dv_testplan
    summary = dict(sections=[dict(id="register_map", status="BLOCKED"),
                             dict(id="rtl_observations", status="PASS")],
                   interfaces=dict(status="PASS"), registers=dict(status="BLOCKED"))
    monkeypatch.setattr("orchestrator_agent.tools.dv_pipeline.run_testplan_doc", lambda *args, **kwargs: summary)
    result = run_dv_testplan(dict(out=str(tmp_path), rtl_graph="graph.json"), StepContext(tmp_path))
    assert result["status"] == "BLOCKED"
    assert "register_map:BLOCKED" in result["summary"]
