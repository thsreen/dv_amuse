"""A request's bus-width words select the RTL configuration, and the 8-bit interface flows to the code stage by itself."""
import json
from pathlib import Path

import pytest

from orchestrator_agent.flow import resolve_args
from orchestrator_agent.request_defines import resolve, source_macros
from orchestrator_agent.tools import run_rtl_extract

UART = Path(__file__).resolve().parents[2] / 'baseline_repos/uart16550/rtl/verilog'
needs_uart = pytest.mark.skipif(not UART.is_dir(), reason='UART baseline RTL unavailable')


def rtl(tmp_path, body):
    path = tmp_path / 'bus_top.v'
    path.write_text(body)
    return [path]


GENERIC = ('module bus_top(input clk, input [7:0] d);\n`ifdef NARROW_DATA_BUS_WIDTH_8\n  wire [2:0] a;\n`else\n  wire [4:0] a;\n`endif\n'
           '`ifdef FIFO_TRIGGER_8\n  wire t;\n`endif\nendmodule\n')


def test_a_width_phrase_selects_the_one_bus_macro_and_never_a_trigger_level(tmp_path):
    files = rtl(tmp_path, GENERIC)
    assert source_macros(files) == ['NARROW_DATA_BUS_WIDTH_8', 'FIFO_TRIGGER_8']
    assert resolve('use the 8 bit version', files) == (['NARROW_DATA_BUS_WIDTH_8'], None)
    assert resolve('the 3 bit version', files) == ([], None)  # no configuration macro for that width: nothing selected, nothing blocked


def test_a_width_phrase_that_matches_several_bus_macros_is_a_question_not_a_guess(tmp_path):
    files = rtl(tmp_path, GENERIC + '`ifdef RX_DATA_WIDTH_8\n`endif\n')
    defines, question = resolve('8 bit please', files)
    assert defines == [] and question and 'NARROW_DATA_BUS_WIDTH_8' in question and 'RX_DATA_WIDTH_8' in question
    assert 'define NARROW_DATA_BUS_WIDTH_8' in question  # the answer is named in the question


def test_a_macro_named_outright_is_selected_and_nothing_without_macros_changes(tmp_path):
    files = rtl(tmp_path, GENERIC)
    assert resolve('define FIFO_TRIGGER_8 and go', files) == (['FIFO_TRIGGER_8'], None)
    assert resolve('build it', rtl(tmp_path, 'module m; endmodule\n')) == ([], None)


def test_the_flow_passes_the_defines_and_an_unset_request_passes_none(tmp_path):
    assert resolve_args({'define': '${rtl_defines:-}'}, {}, 's') == {'define': ''}
    assert resolve_args({'define': '${rtl_defines:-}'}, {'rtl_defines': ['DATA_BUS_WIDTH_8']}, 's') == {'define': ['DATA_BUS_WIDTH_8']}


@needs_uart
def test_the_extraction_step_reports_the_widths_of_the_selected_configuration(tmp_path):
    files = [str(p) for p in sorted(UART.glob('*.v'))]
    base = dict(files=files, top='uart_top', out=str(tmp_path / 'wide'), build=True)
    wide = run_rtl_extract(base, None)
    narrow = run_rtl_extract(dict(base, out=str(tmp_path / 'narrow'), define=['DATA_BUS_WIDTH_8']), None)
    assert wide['status'] == narrow['status'] == 'PASS' and narrow['defines'] == ['DATA_BUS_WIDTH_8']
    widths = lambda folder: {p['name']: p.get('width') for p in json.loads((folder / 'interface_definition.json').read_text())['ports']}
    assert widths(tmp_path / 'wide')['wb_dat_i'] == 32 and widths(tmp_path / 'wide')['wb_adr_i'] == 5
    assert widths(tmp_path / 'narrow')['wb_dat_i'] == 8 and widths(tmp_path / 'narrow')['wb_adr_i'] == 3
    assert 'with defines DATA_BUS_WIDTH_8' in narrow['summary'] and wide['defines'] == []


@needs_uart
def test_a_request_for_8_bit_goes_all_the_way_to_the_interface_the_code_stage_reads(tmp_path):
    """The request -> resolved define -> flow arguments -> interface JSON chain, with no demo path."""
    files = [str(p) for p in sorted(UART.glob('*.v'))]
    defines, question = resolve('use the 8 bit version', [Path(f) for f in files])
    assert question is None and defines == ['DATA_BUS_WIDTH_8']
    args = resolve_args({'files': ['x'], 'top': 'uart_top', 'define': '${rtl_defines:-}', 'out': 'o', 'build': True},
                        {'rtl_defines': defines}, 'rtl_ports')
    out = tmp_path / 'run/rtl'
    result = run_rtl_extract(dict(args, files=files, out=str(out)), None)
    assert result['status'] == 'PASS' and result['defines'] == ['DATA_BUS_WIDTH_8']
    ports = {p['name']: p.get('width') for p in json.loads((out / 'interface_definition.json').read_text())['ports']}
    assert ports['wb_dat_i'] == 8 and ports['wb_dat_o'] == 8  # what the code stage and port comparison then consume


def test_the_ask_card_shows_the_selected_configuration_and_an_open_question(tmp_path):
    from orchestrator_agent import repl
    shown = []
    flow = dict(steps=[dict(id='rtl_ports', tool='rtl_extract', agent='rtl', description='Extract ports')])
    text = repl.ask_card(flow, Path('flow.json'), dict(repo='r', rtl_defines=['DATA_BUS_WIDTH_8']), 'use the 8 bit version', tmp_path)
    assert 'RTL configuration from the request: DATA_BUS_WIDTH_8' in text
    blocked = repl.ask_card(flow, Path('flow.json'), dict(repo='r', rtl_define_question='Name the one you want.'), 'use the 8 bit version', tmp_path)
    assert 'RTL configuration: NOT SET' in blocked and 'blocked until it is named' in blocked
