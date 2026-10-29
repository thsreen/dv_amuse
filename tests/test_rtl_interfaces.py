"""Offline declaration and JSON builder checks for the independent coding flow."""
import hashlib
import json
from pathlib import Path

import pytest

from dv_agent import cli
from dv_agent.cli import main
from rtl_agent.builder import build_interface
from rtl_agent.extractor import extract_interface
from rtl_agent.source import RTLExtractionError


@pytest.fixture
def source(tmp_path):
    def write(text, name="block.sv"):
        path = tmp_path / name
        path.write_text(text)
        return path
    return write


def test_ansi_inheritance_parameters_arrays_and_evidence(source):
    path = source("""module block #(parameter W=8, N=2)(
    input logic clk, rst_n,
    input logic signed [W-1:0] data, other,
    output bit [0:1][3:0] result [N],
    inout wire pad
);
function automatic f(input hidden); f=hidden; endfunction
endmodule
""")
    contract = extract_interface([path], "block", overrides={"W": "12"})
    ports = contract["ports"]
    assert [(p["name"], p["direction"], p["width_bits"]) for p in ports] == [
        ("clk", "input", 1), ("rst_n", "input", 1), ("data", "input", 12),
        ("other", "input", 12), ("result", "output", 8), ("pad", "inout", 1)]
    assert ports[2]["signed"] and ports[3]["signed"]
    assert ports[4]["data_type"] == "bit" and ports[4]["total_bits"] == 16
    assert ports[4]["packed_dimensions"][0]["left"] == 0
    assert ports[4]["unpacked_dimensions"] == [dict(expression="N", left=0, right=1, size=2)]
    evidence = ports[2]["source"]
    assert path.read_text().splitlines()[evidence["line"] - 1] == evidence["quote"]
    assert contract["sources"] == [dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())]


def test_non_ansi_includes_macros_and_optional_ports(source):
    header = source("""`ifndef CFG
`define CFG
`ifdef SMALL
`define WIDTH 4
`elsif MEDIUM
`define WIDTH 6
`else
`define WIDTH 16
`endif
`endif
""", "config.vh")
    path = source("""`include "config.vh"
module block(clk, data, ready
`ifdef EXTRA
, extra
`endif
);
parameter W=`WIDTH;
input clk;
input [W-1:0] data;
output ready;
`ifdef EXTRA
output extra;
`endif
wire ready;
endmodule
""")
    default = extract_interface([path], "block")
    optional = extract_interface([path], "block", defines={"SMALL": "1", "EXTRA": "1"})
    medium = extract_interface([path], "block", defines={"MEDIUM": "1"})
    assert [p["width_bits"] for p in default["ports"]] == [1, 16, 1]
    assert [p["width_bits"] for p in optional["ports"]] == [1, 4, 1, 1]
    assert medium["ports"][1]["width_bits"] == 6
    assert {s["path"] for s in optional["sources"]} == {str(path), str(header)}


def test_parameter_dependencies_and_clog2(source):
    path = source("""module block #(parameter W=8, A=$clog2(W))
      (input [A-1:0] address, output [LOCAL-1:0] data);
    localparam LOCAL=W*2;
    endmodule""")
    result = extract_interface([path], "block", overrides={"W": "32"})
    assert [p["width_bits"] for p in result["ports"]] == [5, 64]
    assert {p["name"]: p["value"] for p in result["parameters"]} == {"W": 32, "A": 5, "LOCAL": 64}
    with pytest.raises(RTLExtractionError, match="local parameter"):
        extract_interface([path], "block", overrides={"LOCAL": "1"})


@pytest.mark.parametrize("text, message", [
    ("module block(input custom_t x); endmodule", "unsupported"),
    ("module block(my_bus.slave bus); endmodule", "unsupported"),
    ("module block(input a=1); endmodule", "unsupported"),
    ("module block(input [UNKNOWN:0] a); endmodule", "unresolved"),
    ("module block(input [8'hff+1:0] a); endmodule", "sized-literal"),
    ("module block(input [2147483647+1:0] a); endmodule", "signed 32-bit"),
    ("module block(input [1/0:0] a); endmodule", "division by zero"),
    ("module block(input a[]); endmodule", "empty"),
    ("module block(input [7:0] a; endmodule", "unclosed"),
    ("module block(a,b); input a; endmodule", "match"),
    ("module block(a); input a; output a; endmodule", "match"),
    ("module block(input a, input a); endmodule", "duplicate"),
    ("module block(input input); endmodule", "identifier"),
    ("module block(inout reg pad); endmodule", "must be a net"),
    ("module block(q); output q; reg [7:0] q; endmodule", "differing"),
    ("module block(q); output q; reg signed q; endmodule", "differing"),
    ("module block(q); output q [2]; reg q [3]; endmodule", "differing"),
    ("module block #(parameter W=8'hff)(input [W*W:0] a); endmodule", "sized untyped"),
    ("module other(input a); endmodule", "found 0"),
    ("module block(input a); endmodule module block(input b); endmodule", "found 2"),
    ("`include \"missing.vh\"\nmodule block(input a); endmodule", "include not found"),
    ("`ifdef X\nmodule block; endmodule", "unterminated conditional"),
    ("`else\nmodule block; endmodule", "unmatched"),
    ("`define X `X\nmodule block(input [`X:0] a); endmodule", "recursive macro"),
    ("`define X(n) n\nmodule block(input [`X(8):0] a); endmodule", "function-like macro"),
    ("module block(input [`MISSING:0] a); endmodule", "undefined macro"),
])
def test_unsupported_or_incomplete_contract_never_succeeds(source, text, message):
    with pytest.raises(RTLExtractionError, match=message):
        extract_interface([source(text)], "block")


def test_include_search_path_and_recursive_include(source, tmp_path):
    header = source("`define WIDTH 6", "width.vh")
    nested = tmp_path / "rtl"
    nested.mkdir()
    path = source('`include "width.vh"\nmodule block(input [`WIDTH-1:0] a); endmodule', "rtl/top.v")
    assert extract_interface([path], "block", include_dirs=[tmp_path])["ports"][0]["width_bits"] == 6
    header.write_text('`include "width.vh"')
    with pytest.raises(RTLExtractionError, match="recursive include"):
        extract_interface([path], "block", include_dirs=[tmp_path])


def test_exponential_macro_expansion_is_bounded(source):
    defines = ["`define M0 1"] + [f"`define M{i} `M{i-1} + `M{i-1}" for i in range(1, 19)]
    text = "\n".join(defines) + "\nmodule block(input [`M18:0] a); endmodule"
    with pytest.raises(RTLExtractionError, match="substitution budget"):
        extract_interface([source(text)], "block")


def test_comments_inactive_branches_and_macro_continuation(source):
    path = source("""// module block(input bogus); endmodule
`define W 4 + \\
4
`ifdef UNDEFINED
`include "absent.vh"
`define IGNORED 2
`endif
module block(input [`W-1:0] a);
/* input not_a_port; */
initial $display("// `NOT_A_MACRO");
endmodule
""")
    assert extract_interface([path], "block")["ports"][0]["width_bits"] == 8


def test_matching_legacy_reg_redeclaration_and_scoped_variables(source):
    path = source("""module block(q); output [3:0] q; reg [3:0] q;
    initial begin reg [7:0] q; end
    endmodule""")
    assert extract_interface([path], "block")["ports"][0]["width_bits"] == 4


def test_integer_typed_sized_parameter(source):
    path = source("module block #(parameter integer W=8'h10)(input [W-1:0] a); endmodule")
    assert extract_interface([path], "block")["ports"][0]["width_bits"] == 16


def test_sized_override_cannot_change_an_untyped_parameters_arithmetic_rules(source):
    path = source("module block #(parameter W=4)(input [W*W:0] a); endmodule")
    with pytest.raises(RTLExtractionError, match="sized untyped parameter overrides"):
        extract_interface([path], "block", overrides={"W": "8'hff"})


def test_json_definition_contains_only_wiring_essentials(source):
    path = source("module block #(parameter data_width=8)(input clk, input [data_width-1:0] data, output ready); endmodule")
    contract = extract_interface([path], "block")
    artifacts = build_interface(contract)
    assert list(artifacts) == ["interface_definition.json"]
    definition = json.loads(artifacts["interface_definition.json"])
    template = json.loads((Path(__file__).parents[1] / "src/rtl_agent/templates/rtl_interface_v0.json").read_text())
    assert set(template) == set(definition) == {"sources", "direction_reference", "parameters", "ports"}
    assert definition["sources"] == ["block.sv"]
    assert definition["parameters"] == [{"name": "DATA_WIDTH", "width": 8}]
    assert definition["ports"][1] == {"name": "data", "direction": "input", "width": 8}
    assert definition["direction_reference"] == "DUT"


def test_optional_sv_export_preserves_directions_arrays_parameters_and_groups(source):
    path = source("""module block #(parameter W=8)(input clk,
        input signed [W-1:0] data, output logic [0:3] ready [2]); endmodule""")
    contract = extract_interface([path], "block", overrides={"W": "12"})
    groups = {"Clock domain": ["clk"], "Data bus": ["data", "ready"]}
    artifacts = build_interface(contract, groups=groups, clock="clk", emit_sv=True)
    sv = artifacts["block_if.sv"]
    assert "logic signed [11:0] data;" in sv and "logic [0:3] ready[0:1];" in sv
    dut, tb, monitor = sv.split("modport dut")[1].split("modport tb")[0], sv.split("modport tb")[1], sv.split("modport monitor")[1]
    assert "input data" in dut and "output ready" in dut
    assert "output data" in tb and "input ready" in tb
    assert "input data" in monitor and "input ready" in monitor
    assert "clocking driver_cb @(posedge clk);" in sv
    assert ".W(12)" in artifacts["block_if_connections.sv"]
    definition = json.loads(artifacts["interface_definition.json"])
    assert definition["groups"] == groups
    assert definition["ports"][2] == dict(name="ready", direction="output", range="[0:3]",
                                          unpacked="[0:1]")


def test_inout_is_a_resolved_net_and_has_no_clock_guess(source):
    contract = extract_interface([source("module block(input clk, inout [3:0] pad); endmodule")], "block")
    sv = build_interface(contract, emit_sv=True)["block_if.sv"]
    assert "tri [3:0] pad;" in sv and sv.count("inout pad") == 2 and "clocking" not in sv
    with pytest.raises(RTLExtractionError, match="bidirectional"):
        build_interface(contract, clock="clk")


@pytest.mark.parametrize("options, message", [
    ({"groups": {"a": ["clk"]}}, "exactly once"),
    ({"groups": {"a": ["clk", "ready", "ready"]}}, "exactly once"),
    ({"groups": {"a": ["clk", "ready", "missing"]}}, "exactly once"),
    ({"groups": {"a": []}}, "nonempty"),
    ({"groups": {}}, "groups must"),
    ({"interface_name": "bad; injected"}, "identifier"),
    ({"interface_name": "module"}, "reserved"),
    ({"interface_name": "always"}, "reserved"),
    ({"clock": "ready"}, "scalar DUT input"),
    ({"clock": "missing"}, "scalar DUT input"),
    ({"edge": "both"}, "clock edge"),
])
def test_builder_rejects_invalid_mapping_or_generated_names(source, options, message):
    contract = extract_interface([source("module block(input clk, output ready); endmodule")], "block")
    with pytest.raises(RTLExtractionError, match=message):
        build_interface(contract, **options)


def test_cli_json_first_and_separate_builder_never_construct_models(source, tmp_path, monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise AssertionError("coding-flow extraction must stay offline")
    monkeypatch.setattr(cli, "MetaClient", explode)
    monkeypatch.setattr(cli, "MetaEmbedder", explode)
    path = source("module block #(parameter W=4)(input clk, output [W-1:0] data); endmodule")
    out = tmp_path / "out"
    assert main(["rtl-interfaces", str(path), "--top", "block", "--out", str(out), "--build"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["artifacts"] == ["rtl_interfaces.json", "interface_definition.json"]
    assert not list(out.glob("*.sv")) and not (out / "graph.json").exists()
    assert main(["build-interface", str(out / "rtl_interfaces.json"), "--out", str(out)]) == 0
    assert json.loads((out / "rtl_interfaces.json").read_text()) == json.loads((out / "interface_definition.json").read_text())
    assert not list(out.glob("*.sv"))


def test_cli_failure_writes_no_partial_outputs(source, tmp_path, capsys):
    path = source("module block(input missing_type x); endmodule")
    out = tmp_path / "out"
    assert main(["rtl-interfaces", str(path), "--top", "block", "--out", str(out), "--build"]) == 2
    assert "unsupported" in capsys.readouterr().err and not out.exists()
    path.write_text("module block(input clk); endmodule")
    assert main(["rtl-interfaces", str(path), "--top", "block", "--out", str(out), "-P", "W"]) == 2
    assert "expected NAME=VALUE" in capsys.readouterr().err


def test_generated_sv_cannot_overwrite_a_dut(source, tmp_path, capsys):
    path = source("module block(input clk); endmodule", "block_if.sv")
    original = path.read_bytes()
    assert main(["rtl-interfaces", str(path), "--top", "block", "--out", str(tmp_path),
                 "--build", "--emit-sv"]) == 2
    assert "overwrite source" in capsys.readouterr().err
    assert path.read_bytes() == original and not (tmp_path / "rtl_interfaces.json").exists()


def test_separate_builder_uses_saved_simple_definition(source, tmp_path, capsys):
    path = source("module block(input [3:0] a); endmodule")
    out = tmp_path / "extract"
    assert main(["rtl-interfaces", str(path), "--top", "block", "--out", str(out)]) == 0
    capsys.readouterr()
    path.unlink()
    dest = tmp_path / "build"
    assert main(["build-interface", str(out / "rtl_interfaces.json"), "--out", str(dest)]) == 0
    definition = json.loads((dest / "interface_definition.json").read_text())
    assert definition["sources"] == ["block.sv"] and definition["ports"][0]["width"] == 4


@pytest.mark.parametrize("bounds", ["[7:0]", "[0:7]", "[-1:-8]", "[1:0][3:0]"])
def test_saved_range_preserves_indexing_without_comment(bounds):
    contract = dict(sources=["block.sv"], parameters=[], ports=[dict(direction="input", range=bounds, name="data")])
    text = build_interface(contract)["interface_definition.json"]
    port = json.loads(text)["ports"][0]
    assert port == dict(direction="input", range=bounds, name="data")
    assert ', "range"' in text and ', "name"' in text


def test_description_is_optional_last_column_and_old_comment_is_removed():
    contract = dict(sources=["block.sv"], parameters=[], ports=[
        dict(direction="input", range="[7:0]", name="data", description="Input data", comment="width=8"),
        dict(direction="input", width=1, name="clk"),
    ])
    text = build_interface(contract)["interface_definition.json"]
    ports = json.loads(text)["ports"]
    assert ports[0]["description"] == "Input data" and list(ports[0])[-1] == "description"
    assert "description" not in ports[1] and all("comment" not in p for p in ports)
    assert build_interface(json.loads(text))["interface_definition.json"] == text


@pytest.mark.parametrize("bounds", ["7:0", "[7]", "[X:0]", "[7:0] trailing", "[1073741824:0]"])
def test_invalid_saved_range_is_rejected(bounds):
    contract = dict(sources=["block.sv"], parameters=[], ports=[dict(direction="input", range=bounds, name="data")])
    with pytest.raises(RTLExtractionError, match="range"):
        build_interface(contract)
