"""The script-chosen quick-testing test: built from what the model established, and passing on the real simulator."""
import json
import os
from pathlib import Path

import pytest

from dv_agent.codegen.contracts import CodePlan
from dv_agent.codegen.quick_basic import TEST_ID, apply_basic_test
from dv_agent.codegen.reasoning import check_hook, unwrap_hook


def fixture_plan(tmp_path):
    from codegen_uart_fixture import create
    repo = create(tmp_path)
    contract = json.loads((tmp_path / 'code_contract.json').read_text())
    for agent in contract['agents']:
        if agent['protocol'] == 'serial':
            agent['idle_values'] = {agent['bindings']['rx']: 1}
    return CodePlan.model_validate(contract), repo


def test_the_test_replaces_the_model_tests_and_routes_and_saves_what_it_set_aside(tmp_path):
    plan, _ = fixture_plan(tmp_path)
    model_tests, model_routes = [t.id for t in plan.tests], [r.id for r in plan.routes]
    model_sequences = [s.id for s in plan.sequences]
    assert apply_basic_test(plan, tmp_path)
    assert [t.id for t in plan.tests] == [TEST_ID] and plan.tests[0].minimum_comparisons == 2
    assert [r.id for r in plan.routes] == [f'{TEST_ID}_transmit', f'{TEST_ID}_receive']
    assert all(s in [x.id for x in plan.sequences] for s in model_sequences)  # the model's sequences stay in the project
    aside = json.loads((tmp_path / 'quick_basic_set_aside.json').read_text())
    assert [t['id'] for t in aside['tests']] == model_tests and [r['id'] for r in aside['routes']] == model_routes
    assert any(q.startswith(f'Quick testing: {TEST_ID} is chosen by script') for q in plan.questions)


def test_the_data_address_condition_comes_from_a_data_path_or_is_the_opposite_of_a_bus_to_bus_route(tmp_path):
    from dv_agent.codegen.contracts import Condition, Route
    from dv_agent.codegen.quick_basic import _data_condition, _setup_operations
    plan, _ = fixture_plan(tmp_path)
    bus = next(a for a in plan.agents if a.protocol == 'wishbone')
    facts = plan.sequences[0].fact_ids
    bank = Condition(agent=bus.id, address=3, mask=128, value=128, initial_value=0)
    plan.routes = [Route(id='bank', expected_agent=bus.id, expected_event='write', expected_address=0, actual_agent=bus.id, actual_event='read',
                         actual_address=0, when=[bank], fact_ids=facts)]
    assert _data_condition(plan, bus, 0, _setup_operations(plan, bus))[0].value == 0
    data = bank.model_copy(update=dict(value=0))
    plan.routes.append(Route(id='path', expected_agent=bus.id, expected_event='write', expected_address=0, actual_agent='serial_link', actual_event='tx',
                             when=[data], fact_ids=facts))
    assert _data_condition(plan, bus, 0, _setup_operations(plan, bus))[0].value == 0
    plan.routes = plan.routes[1:]
    assert _data_condition(plan, bus, 0, _setup_operations(plan, bus))[0].value == 0


def test_the_data_address_can_come_from_a_bus_write_and_read_and_the_condition_from_the_setup(tmp_path):
    from dv_agent.codegen.contracts import Condition, Operation, Route, Sequence
    plan, _ = fixture_plan(tmp_path)
    bus = next(a for a in plan.agents if a.protocol == 'wishbone')
    facts = plan.sequences[0].fact_ids
    bank = Condition(agent=bus.id, address=3, mask=128, value=128, initial_value=0)
    plan.routes = [Route(id='loop', expected_agent=bus.id, expected_event='write', expected_address=0, actual_agent=bus.id, actual_event='read', actual_address=0, fact_ids=facts),
                   Route(id='other', expected_agent=bus.id, expected_event='write', expected_address=1, actual_agent=bus.id, actual_event='read', actual_address=1, when=[bank], fact_ids=facts)]
    sweep = Sequence(id='sweep', agent=bus.id, purpose='sweep', fact_ids=facts, operations=[Operation(kind='write', address=1, data=d) for d in (0, 1, 2)])
    plan.sequences.insert(0, sweep)
    assert _setup_name(plan, bus) == 'initialize_link'  # the sweep is passed over
    assert apply_basic_test(plan, tmp_path)
    receive = plan.routes[1]
    assert receive.actual_address == 0 and plan.tests[0].id == TEST_ID
    assert (receive.when[0].address, receive.when[0].mask, receive.when[0].value) == (3, 128, 0)  # the setup leaves that state


def _setup_name(plan, bus):
    from dv_agent.codegen.quick_basic import _setup_operations
    return _setup_operations(plan, bus).id


def test_a_plan_without_the_parts_it_needs_keeps_the_model_tests_and_says_so(tmp_path):
    plan, _ = fixture_plan(tmp_path)
    plan.routes = []
    tests = [t.id for t in plan.tests]
    assert not apply_basic_test(plan, tmp_path)
    assert [t.id for t in plan.tests] == tests and 'the model tests were kept' in plan.questions[-1]
    assert not (tmp_path / 'quick_basic_set_aside.json').exists()


def test_a_register_mirrored_at_the_data_address_becomes_a_plain_write(tmp_path):
    plan, _ = fixture_plan(tmp_path)
    from dv_agent.codegen.contracts import Operation, Register
    facts = plan.sequences[0].fact_ids
    plan.registers.append(Register(id='aliased', agent=plan.routes[0].expected_agent, address=0, width=8, access='RW', reset=0, mask=255, fact_ids=facts))
    plan.sequences[0].operations.append(Operation(kind='register_write', register_id='aliased', address=0, data=1))
    assert apply_basic_test(plan, tmp_path)
    assert 'aliased' not in [r.id for r in plan.registers]
    assert plan.sequences[0].operations[-1].kind == 'write' and plan.sequences[0].operations[-1].register_id is None


@pytest.mark.parametrize('code', ['task body();\n  x = 1;\nendtask', 'task automatic body();\n  x = 1;\nendtask', 'task body;\n  x = 1;\nendtask : body',
                                  'function void f();\n  x = 1;\nendfunction'])
def test_a_hook_wrapper_is_removed(code):
    assert unwrap_hook(code).strip() == 'x = 1;'


def test_a_hook_that_still_declares_a_task_is_refused_and_plain_statements_pass():
    from types import SimpleNamespace
    hook = SimpleNamespace(id='h', slot='monitor.body')
    assert check_hook('task body();\n  x = 1;\nendtask', hook, None).strip() == 'x = 1;'
    assert unwrap_hook('begin : b\n  x = 1;\nend') == 'begin : b\n  x = 1;\nend'
    with pytest.raises(ValueError, match='statements of its body'):
        check_hook('task helper(int a);\n  x = a;\nendtask', hook, None)


def test_real_uart_script_chosen_test_passes_with_real_comparisons(tmp_path, monkeypatch):
    if os.getenv('DV_AGENT_TEST_SIMULATION') != '1':
        pytest.skip('Set DV_AGENT_TEST_SIMULATION=1 for real Xezim/UVM integration')
    from dv_agent.codegen import build_project
    from dv_agent.codegen.simulator import discover, run_project
    if not os.getenv('XEZIM_UVM_DIR'):
        monkeypatch.setenv('XEZIM_UVM_DIR', str(Path(__file__).resolve().parents[1] / '.deps/uvm-core-2020.3.1/src'))
    if discover()['status'] != 'PASS':
        pytest.fail(str(discover()))
    plan, repo = fixture_plan(tmp_path)
    assert apply_basic_test(plan, tmp_path)
    (tmp_path / 'code_contract.json').write_text(plan.model_dump_json())
    manifest = build_project(tmp_path / 'testplan.json', tmp_path / 'interface.json', tmp_path / 'output', contract_path=tmp_path / 'code_contract.json',
                             rtl_files=list((repo / 'rtl/verilog').glob('*.v')), compile=True)
    assert manifest['compile']['status'] == 'PASS', manifest['compile']
    result = run_project(manifest, regress=True, timeout=60, wave=True)
    assert result['status'] == 'PASS', [(t['name'], t['reason'], t['log']) for t in result['tests']]
    test = result['tests'][0]
    assert test['name'] == TEST_ID and test['scoreboard_comparisons'] == 2 and test['uvm_counts']['ERROR'] == 0
    assert Path(test['waveform']).stat().st_size > 1000 and Path(test['waveform']).read_bytes()[0] == 0  # an FST header block
    assert test['coverage_summary']['assertions_passed'] == test['coverage_summary']['assertions'] > 0
    assert '| Group | Kind | Samples | Coverage |' in Path(test['coverage_report']).read_text()
    assert test['coverage_summary']['groups']
