"""A demo script (data, in RTL port names) becomes a functional-lite demo: named register writes and a packet each way."""
import json
import os
from pathlib import Path

import pytest

from dv_agent.codegen import build_demo
from dv_agent.codegen.contracts import CodePlan
from dv_agent.codegen.demo_contract import build_demo_contract, demo_script_path
from test_codegen import inputs  # noqa: F401  (fixture)


def script(**changes):
    base = {
        'top': 'peripheral',
        'agents': [{'id': 'control', 'protocol': 'wishbone',
                    'bindings': {'addr': 'index', 'wdata': 'push', 'rdata': 'pull', 'sel': 'lanes', 'we': 'writing', 'stb': 'request',
                                 'cyc': 'cycle', 'ack': 'ready'}}],
        'registers': [{'id': 'control_storage', 'agent': 'control', 'address': 1, 'width': 8, 'access': 'RW', 'reset': 0, 'mask': 255}],
        'sequences': [{'id': 'write_once', 'agent': 'control', 'purpose': 'one named register write',
                       'operations': [{'kind': 'register_write', 'register_id': 'control_storage', 'data': 165}]}],
        'tests': [{'id': 'basic_demo', 'stages': [['write_once']], 'drain_cycles': 8, 'minimum_comparisons': 0}]}
    return base | changes


def contract(inputs, **changes):
    _, spec, definition, _, _ = inputs
    return build_demo_contract(spec, definition, {'CH-spec': spec['evidence_index']['CH-spec']['excerpt']}, top='peripheral', script=script(**changes))


def test_every_item_cites_the_demo_fact_and_unowned_inputs_are_held_at_zero(inputs):
    result = contract(inputs)
    plan = CodePlan.model_validate(result)
    assert plan.demo and [a.id for a in plan.agents] == ['control'] and plan.registers[0].id == 'control_storage'
    cited = {result['facts'][0]['id']}
    assert all(set(item['fact_ids']) == cited for key in ('agents', 'registers', 'sequences', 'tests') for item in result[key])
    # 'tick' and 'clear' belong to the common UVCs and every other input is owned by the agent, so nothing else is held here.
    assert result['tie_offs'] == [] and any('Scripted demo' in q for q in result['questions'])


def test_ports_the_script_does_not_own_are_held_at_zero(inputs):
    result = contract(inputs, agents=[dict(script()['agents'][0], bindings={k: v for k, v in script()['agents'][0]['bindings'].items() if k != 'sel'})])
    held = {t['signal'] for t in result['tie_offs']}
    assert held == {'lanes'} and all(t['value'] == 0 for t in result['tie_offs'])


@pytest.mark.parametrize('changes,message', [
    (dict(top='other_design'), 'The demo script is for other_design, not peripheral'),
    (dict(agents=[dict(script()['agents'][0], bindings={'addr': 'no_such_port'})]), r"uses ports the RTL does not have: \['no_such_port'\]"),
    (dict(agents=[dict(script()['agents'][0], bindings={'addr': 'tick'})]), r'binds the clock/reset port'),
])
def test_a_script_that_does_not_fit_the_rtl_is_refused_with_the_reason(inputs, changes, message):
    with pytest.raises(ValueError, match=message):
        contract(inputs, **changes)


def test_the_scripted_demo_builds_with_named_register_writes_and_no_model(inputs, tmp_path):
    root, _, _, _, rtl = inputs
    path = tmp_path / 'peripheral.json'
    path.write_text(json.dumps(script()))
    result = build_demo(root / 'plan.json', root / 'interface.json', root / 'output', rtl_files=[rtl], expected_top='peripheral', script=path)
    assert result['demo'] is True and result['status'] == 'BUILT_NEEDS_REVIEW'
    body = (Path(result['code_dir']) / 'sequences/write_once.svh').read_text()
    assert 'cg_reg_access::write(this,"control_storage",64\'ha5,0);' in body


def test_the_script_for_a_top_is_found_by_name_and_a_missing_one_says_what_to_add(tmp_path, monkeypatch):
    assert demo_script_path('uart_top').name == 'uart_top.json'
    monkeypatch.setenv('DV_AGENT_DEMO_SCRIPTS', str(tmp_path))
    (tmp_path / 'custom_top.json').write_text('{}')
    assert demo_script_path('custom_top') == tmp_path / 'custom_top.json'
    with pytest.raises(ValueError, match=r'No demo script for missing_top: add demo_scripts/missing_top.json'):
        demo_script_path('missing_top')


def test_demo_defines_re_extract_the_interface_and_keep_the_original(tmp_path):
    from orchestrator_agent.actions import apply_demo_defines
    rtl = tmp_path / 'top.v'
    rtl.write_text('module top(input clk,\n`ifdef NARROW\n input [7:0] d,\n`else\n input [31:0] d,\n`endif\n output q);\nendmodule\n')
    from rtl_agent.builder import interface_definition
    from rtl_agent.extractor import extract_interface
    out = tmp_path / 'run'
    (out / 'rtl').mkdir(parents=True)
    path = out / 'rtl/interface_definition.json'
    path.write_text(json.dumps(interface_definition(extract_interface([rtl], 'top', include_dirs=[tmp_path]))))
    wide = {p['name']: p.get('width') for p in json.loads(path.read_text())['ports']}
    demo_script = tmp_path / 'top.json'
    demo_script.write_text(json.dumps({'defines': ['NARROW']}))
    assert apply_demo_defines(out, {'rtl_graph_files': [str(rtl)], 'rtl_top': 'top'}, demo_script) == ['NARROW']
    narrow = {p['name']: p.get('width') for p in json.loads(path.read_text())['ports']}
    assert wide['d'] == 32 and narrow['d'] == 8
    assert json.loads((out / 'rtl/interface_definition.before_demo_defines.json').read_text())['ports'] != json.loads(path.read_text())['ports']
    demo_script.write_text('{}')
    assert apply_demo_defines(out, {'rtl_graph_files': [str(rtl)], 'rtl_top': 'top'}, demo_script) == []  # no defines: nothing changes


def test_real_uart_basic_demo_simulates_a_register_write_and_a_packet_each_way(tmp_path, monkeypatch):
    if os.getenv('DV_AGENT_TEST_SIMULATION') != '1':
        pytest.skip('Set DV_AGENT_TEST_SIMULATION=1 for real Xezim/UVM integration')
    from codegen_uart_fixture import create
    from dv_agent.codegen.simulator import discover, run_project
    if not os.getenv('XEZIM_UVM_DIR'):
        monkeypatch.setenv('XEZIM_UVM_DIR', str(Path(__file__).resolve().parents[1] / '.deps/uvm-core-2020.3.1/src'))
    if discover()['status'] != 'PASS':
        pytest.fail(str(discover()))
    repo = create(tmp_path)
    manifest = build_demo(tmp_path / 'testplan.json', tmp_path / 'interface.json', tmp_path / 'output', rtl_files=list((repo / 'rtl/verilog').glob('*.v')),
                          compile=True, script=demo_script_path('uart_top'))
    assert manifest['compile']['status'] == 'PASS', manifest['compile']
    result = run_project(manifest, regress=True, timeout=90)
    assert result['status'] == 'PASS', [(t['name'], t['reason']) for t in result['tests']]
    # Transmit path, receive path and the line-control read-back: all three only match if the transfers really happened.
    assert [t['scoreboard_comparisons'] for t in result['tests']] == [3]
    assert all(t['uvm_counts']['ERROR'] == 0 and t['uvm_counts']['FATAL'] == 0 for t in result['tests'])
