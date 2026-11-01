"""A common register-write sequence any sequence can call by register name; the write runs on the owning bus agent."""
import json
import os
from pathlib import Path

import pytest

from dv_agent.codegen import build_project
from dv_agent.codegen.contracts import CodePlan
from dv_agent.codegen.render import render
from dv_agent.codegen.validate import validate
from test_codegen import inputs  # noqa: F401  (fixture)


def with_register_write(contract, *, register='control_storage', data=165, extra_ops=()):
    contract = json.loads(json.dumps(contract))
    contract['sequences'][0]['operations'] = [dict(kind='register_write', register_id=register, data=data), *extra_ops]
    return contract


def check(contract, spec, definition):
    plan = CodePlan.model_validate(contract)
    return plan, validate(plan, spec, definition, {'CH-spec': spec['evidence_index']['CH-spec']['excerpt']})


def test_the_generated_access_layer_declares_registers_and_is_included_before_every_sequence(inputs):
    _, spec, definition, contract, _ = inputs
    plan, ports = check(with_register_write(contract), spec, definition)
    artifacts, _ = render(plan, ports)
    access = artifacts['uvm/cg_reg_access.svh']
    assert 'add("control_storage","control",64\'h1,8,"RW",64\'hff,1,64\'h0);' in access
    assert 'static task write(uvm_sequence_base parent, string reg_name, longint unsigned value, int gap_cycles = 0);' in access
    assert 'class cg_reg_write_seq extends uvm_sequence #(cg_item);' in access and 'static task write_all' in access
    package = artifacts[f'{plan.top}_verification_pkg.sv']
    assert package.index('uvm/cg_item.svh') < package.index('uvm/cg_reg_access.svh') < package.index(f'sequences/{plan.sequences[0].id}.svh')


def test_a_sequence_names_the_register_and_the_value_instead_of_a_bus_address(inputs):
    _, spec, definition, contract, _ = inputs
    plan, ports = check(with_register_write(contract), spec, definition)
    artifacts, _ = render(plan, ports)
    body = artifacts[f'sequences/{plan.sequences[0].id}.svh']
    assert 'cg_reg_access::write(this,"control_storage",64\'ha5,0);' in body and 'tr.address' not in body
    test = artifacts[f'tests/{plan.tests[0].id}.svh']
    assert 'cg_reg_map::get_map().bind_sequencer("control",cmn_env.control.sqr);' in test  # the owning agent's sequencer is registered


def test_a_design_without_registers_gets_no_access_layer(inputs):
    _, spec, definition, contract, _ = inputs
    contract = json.loads(json.dumps(contract))
    contract['registers'] = []
    contract['sequences'][0]['operations'] = [dict(kind='write', address=1, data=1)]
    plan, ports = check(contract, spec, definition)
    artifacts, _ = render(plan, ports)
    assert 'uvm/cg_reg_access.svh' not in artifacts and 'bind_sequencer' not in artifacts[f'tests/{plan.tests[0].id}.svh']


@pytest.mark.parametrize('change,message', [
    (dict(register='missing_register'), r"not a declared register: \['control_storage'\]"),
    (dict(data=256), r'does not fit the 8-bit register control_storage'),
])
def test_an_undeclared_register_or_a_value_that_does_not_fit_is_refused_with_the_valid_names(inputs, change, message):
    _, spec, definition, contract, _ = inputs
    with pytest.raises(ValueError, match=message):
        check(with_register_write(contract, **change), spec, definition)


def test_a_read_only_register_and_a_stray_register_name_are_refused(inputs):
    _, spec, definition, contract, _ = inputs
    read_only = with_register_write(contract)
    read_only['registers'][0]['access'] = 'RO'
    with pytest.raises(ValueError, match='read-only register control_storage'):
        check(read_only, spec, definition)
    stray = json.loads(json.dumps(contract))
    stray['sequences'][0]['operations'][0]['register_id'] = 'control_storage'
    with pytest.raises(ValueError, match='Only register_write operations name a register'):
        check(stray, spec, definition)


def test_real_uart_registers_are_written_through_the_common_sequence_from_two_agents(tmp_path, monkeypatch):
    """The UART acceptance flow with its raw bus writes replaced by named register writes; the same scoreboard outcome proves the writes happened."""
    if os.getenv('DV_AGENT_TEST_SIMULATION') != '1':
        pytest.skip('Set DV_AGENT_TEST_SIMULATION=1 for real Xezim/UVM integration')
    from codegen_uart_fixture import create
    from dv_agent.codegen.simulator import discover, run_project
    if not os.getenv('XEZIM_UVM_DIR'):
        monkeypatch.setenv('XEZIM_UVM_DIR', str(Path(__file__).resolve().parents[1] / '.deps/uvm-core-2020.3.1/src'))
    if discover()['status'] != 'PASS':
        pytest.fail(str(discover()))
    repo = create(tmp_path)
    contract = json.loads((tmp_path / 'code_contract.json').read_text())
    for agent in contract['agents']:
        if agent['protocol'] == 'serial':
            agent['idle_values'] = {agent['bindings']['rx']: 1}
    evidence = contract['sequences'][0]['fact_ids']
    # Write-only so the scoreboard does not predict reads of the aliased low addresses.
    contract['registers'] += [dict(id=name, agent='register_bus', address=address, width=8, access='WO', reset=None, mask=255, fact_ids=evidence)
                              for name, address in (('divisor_low', 0), ('divisor_high', 1), ('fifo_control', 2))]
    write = lambda register, data: dict(kind='register_write', register_id=register, data=data)
    sequences = {s['id']: s for s in contract['sequences']}
    sequences['initialize_link']['operations'] = [write('line_control', 131), write('divisor_high', 0), write('divisor_low', 2),
                                                  write('line_control', 3), write('divisor_high', 0), write('fifo_control', 6)]
    # Called from a sequence on the serial agent: the write still goes out on the register bus.
    sequences['receive_directed']['operations'] = [write('fifo_control', 6), *sequences['receive_directed']['operations']]
    (tmp_path / 'code_contract.json').write_text(json.dumps(contract))
    manifest = build_project(tmp_path / 'testplan.json', tmp_path / 'interface.json', tmp_path / 'output',
                             contract_path=tmp_path / 'code_contract.json', rtl_files=list((repo / 'rtl/verilog').glob('*.v')), compile=True)
    assert manifest['compile']['status'] == 'PASS', manifest['compile']
    code = Path(manifest['code_dir'])
    assert 'cg_reg_access::write(this,"divisor_low"' in (code / 'sequences/initialize_link.svh').read_text()
    assert 'cg_reg_access::write(this,"fifo_control"' in (code / 'sequences/receive_directed.svh').read_text()
    result = run_project(manifest, regress=True, timeout=60)
    assert result['status'] == 'PASS', [(t['name'], t['reason'], t['log']) for t in result['tests']]
    assert [t['scoreboard_comparisons'] for t in result['tests']] == [3, 4]
    assert all(t['uvm_counts']['ERROR'] == 0 and t['uvm_counts']['FATAL'] == 0 for t in result['tests'])
