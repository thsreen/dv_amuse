"""Script-owned names and shapes in model answers, using the shapes real runs produced."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dv_agent.codegen.defer_unsupported import defer_unknown_agents
from dv_agent.codegen.normalize import agent_alias, normalize_fragment, normalize_interface_unit
from dv_agent.codegen.units import InterfaceUnit
from dv_agent.codegen.workplan import Fragment

QUOTE = 'a quoted sentence'
FACT = dict(id='f1', statement='s', source_id='CH', quote=QUOTE, plan_pointer='/p')
# The 8-bit configuration: the byte-select port keeps its 4 bits, the data bus is 8.
NARROW = {'wb_adr_i': ('input', 3), 'wb_dat_i': ('input', 8), 'wb_dat_o': ('output', 8), 'wb_sel_i': ('input', 4), 'wb_we_i': ('input', 1),
          'wb_stb_i': ('input', 1), 'wb_cyc_i': ('input', 1), 'wb_ack_o': ('output', 1), 'int_o': ('output', 1)}
PORTS = {n: dict(name=n, direction=d, width=w) for n, (d, w) in NARROW.items()}
BUS = [n for n in NARROW if n != 'int_o']


def unit(**fields):
    return InterfaceUnit.model_validate(dict(facts=[FACT]) | fields)


def task(name='wishbone_bus_interface', signals=tuple(BUS)):
    return SimpleNamespace(id=name, signals=list(signals))


def spec_named_custom_bus():
    """Run 0949: the repair left the bus as `custom`, its roles the spec's names, with body hooks."""
    return dict(id='collateral_wishbone_bus_interface', protocol='custom', fact_ids=['f1'],
                bindings={'WB_ADDR_I': 'wb_adr_i', 'WB_SEL_I': 'wb_sel_i', 'WB_DAT_I': 'wb_dat_i', 'WB_DAT_O': 'wb_dat_o', 'WB_WE_I': 'wb_we_i',
                          'WB_STB_I': 'wb_stb_i', 'WB_CYC_I': 'wb_cyc_i', 'WB_ACK_O': 'wb_ack_o'})


def test_the_real_degraded_bus_becomes_the_built_in_8_bit_bus_with_its_byte_select_held():
    answer = unit(agents=[spec_named_custom_bus()], hooks=[
        dict(id='h_drive', target='collateral_wishbone_bus_interface', slot='driver.body', purpose='drive', fact_ids=['f1']),
        dict(id='h_watch', target='collateral_wishbone_bus_interface', slot='monitor.body', purpose='watch', fact_ids=['f1'])])
    normalize_interface_unit(answer, task(), PORTS, 'full_agent')
    agent = answer.agents[0]
    assert agent.id == 'wishbone_bus_interface' and agent.protocol == 'wishbone' and answer.hooks == []
    assert agent.bindings == {'addr': 'wb_adr_i', 'wdata': 'wb_dat_i', 'rdata': 'wb_dat_o', 'we': 'wb_we_i', 'stb': 'wb_stb_i', 'cyc': 'wb_cyc_i', 'ack': 'wb_ack_o'}
    assert [(t.signal, t.value) for t in answer.tie_offs] == [('wb_sel_i', 0)] and answer.tie_offs[0].fact_ids == ['f1']
    assert any('wb_sel_i is held at 0' in q for q in answer.questions) and any('built-in wishbone' in q for q in answer.questions)


def test_a_32_bit_bus_keeps_its_byte_select_and_an_idle_value_on_a_held_port_goes_with_it():
    wide = dict(PORTS, wb_dat_i=dict(direction='input', width=32), wb_dat_o=dict(direction='output', width=32))
    answer = unit(agents=[spec_named_custom_bus()])
    normalize_interface_unit(answer, task(), wide, 'full_agent')
    assert answer.agents[0].bindings['sel'] == 'wb_sel_i' and answer.tie_offs == []
    held = unit(agents=[dict(spec_named_custom_bus(), idle_values={'wb_sel_i': 0})])
    normalize_interface_unit(held, task(), PORTS, 'full_agent')
    assert held.agents[0].idle_values == {}


def test_an_answer_with_no_agent_gets_one_from_its_ports_where_the_assessment_asked_for_it():
    """Every run: the output-only interface came back with no agent and cost a repair."""
    answer = unit()
    normalize_interface_unit(answer, task('interrupt_output', ['int_o']), PORTS, 'passive_agent')
    agent = answer.agents[0]
    assert (agent.id, agent.protocol, agent.active, agent.coverage_enabled) == ('interrupt_output', 'custom', False, False)
    assert agent.bindings == {'int_o': 'int_o'} and agent.fact_ids == ['f1'] and any('declared from its ports' in q for q in answer.questions)
    utility = unit()
    normalize_interface_unit(utility, task('interrupt_output', ['int_o']), PORTS, 'utility_config')
    assert utility.agents == []  # the assessment did not ask for an agent


def test_agent_names_resolve_only_on_an_exact_match_after_stripping():
    ids = {'wishbone_bus_interface', 'uart_serial_data'}
    assert agent_alias('collateral_wishbone_bus_interface', ids) == 'wishbone_bus_interface'
    assert agent_alias('uart_serial_data_agent', ids) == 'uart_serial_data'
    assert agent_alias('wishbone_clock_agent', ids) == 'wishbone_clock_agent'  # invented: never mapped onto a real agent


def fragment(**fields):
    return Fragment.model_validate(dict(facts=[FACT]) | fields)


def test_a_feature_answer_uses_the_real_agents_and_a_clashing_fact_gets_a_new_id():
    answer = fragment(
        checks=[dict(id='c', agent='collateral_bus', kind='known_controls', fact_ids=['f1'])],
        sequences=[dict(id='s', agent='bus_agent', purpose='p', fact_ids=['f1'], operations=[dict(kind='idle', cycles=1)])],
        routes=[dict(id='r', expected_agent='bus_agent', expected_event='write', actual_agent='link', actual_event='tx', mask=255, fact_ids=['f1'],
                     when=[dict(agent='collateral_bus', address=3, mask=1, value=0)])])
    renamed = normalize_fragment(answer, ['bus', 'link'], {'f1': dict(FACT, statement='another fact under the same label')})
    assert answer.checks[0].agent == answer.sequences[0].agent == answer.routes[0].expected_agent == answer.routes[0].when[0].agent == 'bus'
    assert renamed == {'f1': 'f1_2'} and answer.facts[0].id == 'f1_2' and answer.checks[0].fact_ids == ['f1_2'] and answer.routes[0].fact_ids == ['f1_2']
    same = fragment()
    assert normalize_fragment(same, ['bus'], {'f1': dict(FACT)}) == {} and same.facts[0].id == 'f1'  # an identical fact merges


def test_quick_testing_defers_a_bus_check_on_a_non_bus_agent_and_a_sequence_on_a_missing_agent():
    answer = fragment(checks=[dict(id='bad', agent='link', kind='known_controls', fact_ids=['f1']), dict(id='good', agent='bus', kind='known_controls', fact_ids=['f1'])],
                      sequences=[dict(id='lost', agent='clock_agent', purpose='p', fact_ids=['f1'], operations=[dict(kind='idle', cycles=1)])],
                      step_implementations=[dict(step='check_steps/0', component_ids=['bad'], question=''), dict(step='stimulus_steps/0', component_ids=['lost'], question='')])
    dropped = defer_unknown_agents(answer, ['bus', 'link'], [], bus_ids=['bus'])
    assert set(dropped) == {'bad', 'lost'} and [c.id for c in answer.checks] == ['good'] and answer.sequences == []
    assert all(m.question.startswith('Deferred:') for m in answer.step_implementations)


def test_real_uart_custom_agents_without_hooks_compile_and_simulate_beside_the_built_in_ones(tmp_path, monkeypatch):
    """The last run's shape: modem and interrupt agents are custom with no hooks. The template defaults are enough to run."""
    if os.getenv('DV_AGENT_TEST_SIMULATION') != '1':
        pytest.skip('Set DV_AGENT_TEST_SIMULATION=1 for real Xezim/UVM integration')
    from codegen_uart_fixture import create
    from dv_agent.codegen import build_project
    from dv_agent.codegen.simulator import discover, run_project
    if not os.getenv('XEZIM_UVM_DIR'):
        monkeypatch.setenv('XEZIM_UVM_DIR', str(Path(__file__).resolve().parents[1] / '.deps/uvm-core-2020.3.1/src'))
    if discover()['status'] != 'PASS':
        pytest.fail(str(discover()))
    repo = create(tmp_path)
    contract = json.loads((tmp_path / 'code_contract.json').read_text())
    evidence = contract['sequences'][0]['fact_ids']
    for agent in contract['agents']:
        if agent['protocol'] == 'serial':
            agent['idle_values'] = {agent['bindings']['rx']: 1}
    modem = ['rts_pad_o', 'cts_pad_i', 'dtr_pad_o', 'dsr_pad_i', 'ri_pad_i', 'dcd_pad_i']
    contract['agents'] += [dict(id='modem_control_status', protocol='custom', bindings={n: n for n in modem}, fact_ids=evidence, coverage_enabled=False),
                           dict(id='interrupt_output', protocol='custom', bindings={'int_o': 'int_o'}, fact_ids=evidence, active=False, coverage_enabled=False)]
    contract['tie_offs'] = [t for t in contract['tie_offs'] if t['signal'] not in modem]
    contract['coverage'] = [dict(id='line_format', agent='register_bus', fact_ids=['fact_2'], sample_kinds=[1, 2], sample_address=3,
                                 points=[dict(name='access', field='kind', mask=3, bins=[dict(name='writes', values=[1])])])]
    (tmp_path / 'code_contract.json').write_text(json.dumps(contract))
    manifest = build_project(tmp_path / 'testplan.json', tmp_path / 'interface.json', tmp_path / 'output', contract_path=tmp_path / 'code_contract.json',
                             rtl_files=list((repo / 'rtl/verilog').glob('*.v')), compile=True)
    assert manifest['compile']['status'] == 'PASS', manifest['compile']
    driver = (Path(manifest['code_dir']) / 'uvm/modem_control_status_driver.svh').read_text()
    assert 'repeat (tr.cycles) @(posedge cfg.vif.clk);' in driver and 'cfg.vif.cts_pad_i = ' in driver and 'cfg.vif.rts_pad_o =' not in driver
    assert not (Path(manifest['code_dir']) / 'uvm/interrupt_output_driver.svh').exists()
    result = run_project(manifest, regress=True, timeout=60)
    assert result['status'] == 'PASS', [(t['name'], t['reason']) for t in result['tests']]
    assert [t['scoreboard_comparisons'] for t in result['tests']] == [3, 4]


def test_an_interface_name_that_would_collide_with_the_environment_is_renamed_before_any_unit_uses_it():
    """Run 1328: modem_control_flow_control ends like the environment's <agent>_control members; no repair could fix it."""
    from dv_agent.codegen.normalize import safe_interface_ids
    from dv_agent.codegen.validate import agent_id_is_free
    tasks = [SimpleNamespace(id=n) for n in ('modem_control_flow_control', 'sb', 'bus', 'x_control', 'x_control_if')]
    safe_interface_ids(tasks)
    names = [t.id for t in tasks]
    assert names[:3] == ['modem_control_flow_control_if', 'sb_if', 'bus'] and names[3] == 'x_control_if_x'
    assert all(agent_id_is_free(n) for n in names) and len(names) == len(set(names))
