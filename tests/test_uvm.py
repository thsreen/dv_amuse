"""UVM coding-flow scaffold and plan-bound control checks."""
import json
import re

import pytest

from dv_agent.cli import main
from dv_agent.core.llm import LLMResult
from dv_agent.uvm import build_uvm, load_agent_template, write_uvm


DEFINITION = {
    "sources": ["top.sv"], "direction_reference": "DUT", "parameters": [],
    "ports": [
        {"direction": "input", "width": 1, "name": "clk"},
        {"direction": "input", "width": 1, "name": "rst_n"},
        {"direction": "input", "width": 8, "name": "data"},
        {"direction": "input", "width": 1, "name": "valid"},
        {"direction": "output", "width": 1, "name": "ready"},
    ],
}
PLAN = {"sections": [
    {"id": "strategy", "strategy": {"agents": [
        {"name": "bus", "cited_chunk_ids": ["chunk-1"],
         "sequences": [{"name": "Send Data", "purpose": "exercise transfer"}]}]}},
    {"id": "configurations", "configurations": [
        {"field_id": "mode", "legal_values": ["0", "1"], "cited_chunk_ids": ["chunk-1"]}]},
]}


class FakeLLM:
    model = "fake"

    def __init__(self, values):
        self.values = values
        self.calls = []

    def structured(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResult(data={"sequences": [{
            "name": "Send Data", "drive_values": self.values, "cited_chunk_ids": ["chunk-1"]}]},
            model=self.model, response_id="r1")


def _check_package(artifacts, package, includes):
    pkg = artifacts[package]
    assert re.search(r"(?m)^\s*class\s+", pkg) is None
    found = [name for name in re.findall(r'`include "([^"]+\.svh)"', pkg)
             if name != "uvm_macros.svh"]
    assert found == includes
    for include in found:
        path = include if package == "demo_pkg.sv" else package.rsplit("/", 1)[0] + "/" + include
        body = artifacts[path]
        assert len(re.findall(r"(?m)^\s*class\s+\w+\s+extends\b", body)) == 1
        assert len(re.findall(r"(?m)^\s*endclass\b", body)) == 1


def test_scaffold_has_configurable_sequence_and_review_boundary():
    artifacts, manifest = build_uvm(DEFINITION, prefix="demo", clock="clk", reset="rst_n",
                                    reset_active="low", plan=PLAN)
    assert {
        "demo_if.sv", "demo_pkg.sv", "uvm_manifest.json", "common_uvc/README.md",
        "common_uvc/clock/clock_if.sv", "common_uvc/clock/clock_pkg.sv",
        "common_uvc/reset/reset_if.sv", "common_uvc/reset/reset_pkg.sv"} <= set(artifacts)
    _check_package(artifacts, "demo_pkg.sv",
                   [f"uvm/demo_{name}.svh" for name in
                    ("item", "cfg", "sequencer", "driver", "monitor", "scoreboard", "agent",
                     "env", "base_seq", "send_data_seq", "test")])
    _check_package(artifacts, "common_uvc/clock/clock_pkg.sv",
                   [f"clock_{name}.svh" for name in ("cfg", "tick", "driver", "monitor", "agent")])
    _check_package(artifacts, "common_uvc/reset/reset_pkg.sv",
                   [f"reset_{name}.svh" for name in
                    ("cfg", "item", "sequencer", "driver", "monitor", "agent", "pulse_seq")])
    pkg = artifacts["demo_pkg.sv"]
    assert "class demo_driver extends uvm_driver #(demo_item);" in artifacts["uvm/demo_driver.svh"]
    assert "class demo_monitor extends uvm_component;" in artifacts["uvm/demo_monitor.svh"]
    assert "class demo_scoreboard extends uvm_component;" in artifacts["uvm/demo_scoreboard.svh"]
    assert "class demo_env extends uvm_env;" in artifacts["uvm/demo_env.svh"]
    assert "class demo_send_data_seq extends demo_base_seq;" in artifacts["uvm/demo_send_data_seq.svh"]
    assert "bit enable_send_data = 0;" in artifacts["uvm/demo_cfg.svh"]
    assert "int unsigned count_send_data = 1;" in artifacts["uvm/demo_cfg.svh"]
    assert "bit enable_config_mode = 0;" in artifacts["uvm/demo_cfg.svh"]
    assert "longint unsigned config_mode_value = 0;" in artifacts["uvm/demo_cfg.svh"]
    assert "if (cfg.enable_send_data)" in artifacts["uvm/demo_test.svh"]
    assert "if (cfg.drive_data)" in artifacts["uvm/demo_driver.svh"]
    assert "virtual function void check_sample(demo_item tr);" in artifacts["uvm/demo_scoreboard.svh"]
    assert "cfg.vif.data <= tr.data;" in artifacts["uvm/demo_driver.svh"]
    assert "cfg.vif.rst_n <=" not in artifacts["uvm/demo_driver.svh"]
    assert "import clock_pkg::*;" in pkg and "import reset_pkg::*;" in pkg
    assert "clock_uvc = clock_agent::type_id::create" in artifacts["uvm/demo_test.svh"]
    assert "reset_seq.start(reset_uvc.sqr);" in artifacts["uvm/demo_test.svh"]
    assert "reset_control.auto_pulse" in artifacts["uvm/demo_test.svh"]
    assert "reset_control.active_level = 1'b0;" in artifacts["uvm/demo_test.svh"]
    assert "assign dut_bus.clk = clock_bus.clk;" in artifacts["common_uvc/README.md"]
    assert "assign dut_bus.rst_n = reset_bus.reset;" in artifacts["common_uvc/README.md"]
    assert "duty_cycle_pct = 50" in artifacts["common_uvc/clock/clock_cfg.svh"]
    assert "class reset_pulse_seq" in artifacts["common_uvc/reset/reset_pulse_seq.svh"]
    assert "bit auto_pulse = 1;" in artifacts["common_uvc/reset/reset_cfg.svh"]
    assert manifest["plan_configurations"][0]["field_id"] == "mode"
    assert manifest["plan_configurations"][0]["cfg_value"] == "config_mode_value"
    assert manifest["status"] == "NEEDS_REVIEW"


def test_optional_model_only_gets_plan_and_controls_are_bounded():
    llm = FakeLLM({"data": 255, "valid": 1})
    artifacts, manifest = build_uvm(DEFINITION, prefix="demo", clock="clk", plan=PLAN, llm=llm)
    assert "tr.data = 8'd255;" in artifacts["uvm/demo_send_data_seq.svh"]
    assert manifest["llm"]["response_id"] == "r1"
    assert len(llm.calls) == 1
    assert "plan_sections" in llm.calls[0]["payload"]
    assert "sources" not in llm.calls[0]["payload"]
    for bad in ({"data": 256}, {"ready": 1}, {"clk": 1}, {"data": -1}):
        with pytest.raises(ValueError, match="invalid control"):
            build_uvm(DEFINITION, prefix="demo", clock="clk", plan=PLAN, llm=FakeLLM(bad))


def test_agent_template_arguments_rename_and_fill_simple_or_complex_slots():
    args = {
        "template_id": "uvm_agent_v1",
        "name": "custom",
        "custom": {
            "driver.declarations": "int unsigned {{UVC_NAME}}_driven_items;",
            "driver.drive": "{{UVC_NAME}}_driven_items++;",
            "scoreboard.declarations": "bit expected_ready;",
            "scoreboard.check": "if (tr.ready !== expected_ready) `uvm_error(\"CHECK\", \"ready mismatch\")",
        },
        "sequences": {"Send Data": {"configure": "tr.valid = 1'b1; // {{SEQUENCE_ID}}"}},
        "cited_chunk_ids": ["chunk-1"],
    }
    artifacts, manifest = build_uvm(DEFINITION, prefix=None, clock="clk", plan=PLAN, agent_args=args)
    assert "class custom_driver" in artifacts["uvm/custom_driver.svh"]
    assert "custom_driven_items" in artifacts["uvm/custom_driver.svh"]
    assert "custom_driven_items++;" in artifacts["uvm/custom_driver.svh"]
    assert "bit expected_ready;" in artifacts["uvm/custom_scoreboard.svh"]
    assert "ready mismatch" in artifacts["uvm/custom_scoreboard.svh"]
    assert "tr.valid = 1'b1; // send_data" in artifacts["uvm/custom_send_data_seq.svh"]
    assert manifest["agent_template"]["id"] == "uvm_agent_v1"
    assert manifest["agent_arguments"]["custom_slots"] == [
        "driver.declarations", "driver.drive", "scoreboard.check", "scoreboard.declarations"]
    assert manifest["agent_arguments"]["cited_chunk_ids"] == ["chunk-1"]
    assert "uvm_agent_template/template.json" in artifacts
    assert load_agent_template()["custom_slots"]["scoreboard.check"]
    assert "class custom_driver" not in artifacts["custom_pkg.sv"]


def test_agent_template_arguments_reject_unknown_slots_and_class_injection():
    base = {"template_id": "uvm_agent_v1"}
    for bad in (
        {"template_id": "wrong"},
        base | {"custom": {"unknown": "foo();"}},
        base | {"custom": {"driver.drive": "endclass"}},
        base | {"sequences": {"missing": {"configure": "tr.valid=1;"}}},
        base | {"cited_chunk_ids": ["missing"]},
    ):
        with pytest.raises(ValueError):
            build_uvm(DEFINITION, prefix="demo", clock="clk", plan=PLAN, agent_args=bad)


def test_common_uvcs_are_identical_across_projects_and_polarity_is_explicit():
    low, _ = build_uvm(DEFINITION, prefix="first", clock="clk", reset="rst_n",
                       reset_active="low")
    high, _ = build_uvm(DEFINITION, prefix="second", clock="clk", reset="rst_n",
                        reset_active="high")
    for name in ("common_uvc/clock/clock_if.sv", "common_uvc/clock/clock_pkg.sv",
                 "common_uvc/reset/reset_if.sv", "common_uvc/reset/reset_pkg.sv"):
        assert low[name] == high[name]
    assert "reset_control.active_level = 1'b0;" in low["uvm/first_test.svh"]
    assert "reset_control.active_level = 1'b1;" in high["uvm/second_test.svh"]


def test_invalid_wiring_and_overwrite_are_refused(tmp_path):
    with pytest.raises(ValueError, match="clock"):
        build_uvm(DEFINITION, prefix="demo", clock="ready")
    with pytest.raises(ValueError, match="bidirectional"):
        build_uvm(DEFINITION | {"ports": DEFINITION["ports"] +
                  [{"direction": "inout", "width": 1, "name": "pad"}]}, prefix="demo", clock="clk")
    with pytest.raises(ValueError, match="unpacked"):
        build_uvm(DEFINITION | {"ports": DEFINITION["ports"][:-1] +
                  [{"direction": "output", "width": 1, "unpacked": "[1:0]", "name": "ready"}]},
                  prefix="demo", clock="clk")
    with pytest.raises(ValueError, match="reset-active"):
        build_uvm(DEFINITION, prefix="demo", clock="clk", reset="rst_n")
    with pytest.raises(ValueError, match="reset-active"):
        build_uvm(DEFINITION, prefix="demo", clock="clk", reset_active="low")
    artifacts, _ = build_uvm(DEFINITION, prefix="demo", clock="clk")
    out = tmp_path / "out"
    write_uvm(out, artifacts, inputs=[])
    with pytest.raises(ValueError, match="exists"):
        write_uvm(out, artifacts, inputs=[])
    assert (out / "demo_pkg.sv").read_text() == artifacts["demo_pkg.sv"]
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "common_uvc").symlink_to(out / "common_uvc", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        write_uvm(linked, artifacts, inputs=[])


def test_cli_build_uvm_offline(tmp_path, capsys):
    interface = tmp_path / "interface_definition.json"
    interface.write_text(json.dumps(DEFINITION))
    plan = tmp_path / "testplan_doc.json"
    plan.write_text(json.dumps(PLAN))
    out = tmp_path / "uvm"
    assert main(["build-uvm", str(interface), "--out", str(out), "--prefix", "demo",
                 "--clock", "clk", "--testplan", str(plan)]) == 0
    assert (out / "demo_pkg.sv").exists()
    assert (out / "uvm/demo_driver.svh").exists()
    assert (out / "common_uvc/clock/clock_pkg.sv").exists()
    assert (out / "common_uvc/reset/reset_pkg.sv").exists()
    assert json.loads((out / "uvm_manifest.json").read_text())["plan_sequences"][0]["name"] == "Send Data"
    assert main(["build-uvm", str(interface), "--out", str(out), "--prefix", "demo",
                 "--clock", "clk"]) == 2
    assert "exists" in capsys.readouterr().err


def test_cli_accepts_template_arguments_file_without_prefix(tmp_path):
    interface = tmp_path / "interface_definition.json"
    interface.write_text(json.dumps(DEFINITION))
    args = tmp_path / "agent_args.json"
    args.write_text(json.dumps({"template_id": "uvm_agent_v1", "name": "renamed",
                                "custom": {"monitor.sample": "tr.ready = cfg.vif.ready;"}}))
    out = tmp_path / "generated"
    assert main(["build-uvm", str(interface), "--out", str(out), "--clock", "clk",
                 "--agent-args", str(args)]) == 0
    assert (out / "renamed_pkg.sv").exists()
    assert "tr.ready = cfg.vif.ready;" in (out / "uvm/renamed_monitor.svh").read_text()
    assert (out / "uvm_agent_template/template.json").exists()
