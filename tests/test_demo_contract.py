"""Demo testbench: connectivity and a running simulation, built without a model."""
import json
from pathlib import Path

import pytest

from dv_agent.codegen import build_demo
from dv_agent.codegen.contracts import CodePlan
from dv_agent.codegen.demo_contract import DEMO_NOTE, build_demo_contract, demo_hook_code
from test_codegen import inputs  # noqa: F401  (fixture)


def demo(inputs, **kwargs):
    root, _, _, _, rtl = inputs
    return build_demo(root / 'plan.json', root / 'interface.json', root / 'output', rtl_files=[rtl], expected_top='peripheral', **kwargs)


def test_demo_builds_with_no_model_and_marks_everything_as_a_demo(inputs):
    result = demo(inputs)
    assert result['demo'] is True and result['status'] == 'BUILT_NEEDS_REVIEW' and result['compile']['status'] == 'NOT_RUN'
    root = inputs[0]
    contract = json.loads((root / 'output/demo_contract.json').read_text())
    assert contract['demo'] is True and DEMO_NOTE in contract['questions']
    assert (contract['clock'], contract['reset'], contract['reset_active']) == ('tick', 'clear', 'high')  # from the plan's clock/reset groups
    assert contract['tests'][0]['minimum_comparisons'] == 0
    assert contract['routes'] if 'routes' in contract else True  # absent: no routes, registers, checks or coverage
    for absent in ('routes', 'registers', 'checks', 'coverage'):
        assert not contract.get(absent)


def test_every_remaining_port_gets_an_agent_with_an_idle_driver_and_a_passive_monitor(inputs):
    root, spec, definition, _, _ = inputs
    contract = build_demo_contract(spec, definition, {'CH-spec': spec['evidence_index']['CH-spec']['excerpt']}, top='peripheral')
    plan = CodePlan.model_validate(contract)
    bound = {name for a in plan.agents for name in a.bindings.values()}
    assert bound == {p['name'] for p in definition['ports']} - {'tick', 'clear'}  # nothing left unowned or twice-owned
    agent = plan.agents[0]
    assert agent.protocol == 'custom' and agent.active and not agent.coverage_enabled
    ports = {p['name']: p for p in definition['ports']}
    code = demo_hook_code(plan, ports)
    driver = next(v for k, v in code.items() if k.endswith('_driver_hook'))
    assert 'cfg.vif' not in driver.replace('cfg.vif.clk', '') and 'repeat (req.cycles) @(posedge cfg.vif.clk);' in driver  # defaults come from drive_reset_values
    assert next(v for k, v in code.items() if k.endswith('_monitor_hook')).strip().startswith('// demo')


def test_demo_files_are_generated_and_nothing_functional_is_claimed(inputs):
    result = demo(inputs)
    code = Path(result['code_dir'])
    assert (code / 'common_uvc/common/common_env.svh').is_file() and (code / 'tests/demo_smoke.svh').is_file()
    test = (code / 'tests/demo_smoke.svh').read_text()
    assert 'cmn_env.cmn_agent.apply_reset();' in test and 'cmn_cfg.bind_reset(' in test  # clock and reset come from the common UVCs
    assert not list((code / 'uvm').glob('*coverage*')) or all('cg_system' not in p.name for p in (code / 'uvm').glob('*'))
    assert [t['name'] for t in result['tests']] == ['demo_smoke'] and result['tests'][0]['minimum_comparisons'] == 0


def test_a_plan_without_interface_groups_falls_back_to_a_cited_documented_item(inputs):
    root, spec, definition, _, _ = inputs
    spec = json.loads(json.dumps(spec))
    spec.pop('interfaces')
    sources = {'CH-spec': spec['evidence_index']['CH-spec']['excerpt']}
    # no clock/reset groups either: the names decide, and the guess is recorded as a question
    contract = build_demo_contract(spec, dict(definition, ports=[dict(p, name={'tick': 'clk_i', 'clear': 'rst_n'}.get(p['name'], p['name'])) for p in definition['ports']]),
                                   sources, top='peripheral')
    assert (contract['clock'], contract['reset'], contract['reset_active']) == ('clk_i', 'rst_n', 'low')
    assert contract['facts'][0]['id'] == 'demo_basis' and contract['facts'][0]['plan_pointer'].startswith('/sections/')
    assert any('assumed low from its name' in q for q in contract['questions'])


def test_demo_refuses_when_nothing_can_be_driven_or_no_clock_is_found(inputs):
    root, spec, definition, _, _ = inputs
    sources = {'CH-spec': spec['evidence_index']['CH-spec']['excerpt']}
    outputs_only = dict(definition, ports=[dict(p, direction='output') if p['name'] not in ('tick', 'clear') else p for p in definition['ports']])
    with pytest.raises(ValueError, match='at least one DUT input'):
        build_demo_contract(spec, outputs_only, sources, top='peripheral')
    nameless = dict(definition, ports=[dict(p, name='p%d' % i) for i, p in enumerate(definition['ports'])])
    spec = json.loads(json.dumps(spec)); spec.pop('interfaces')
    with pytest.raises(ValueError, match='one clock and one reset'):
        build_demo_contract(spec, nameless, sources, top='peripheral')


def test_the_simulator_does_not_demand_functional_evidence_from_a_demo(inputs, monkeypatch):
    from dv_agent.codegen import simulator
    result = demo(inputs)
    log = ('UVM_INFO : 1\nUVM_WARNING : 0\nUVM_ERROR : 0\nUVM_FATAL : 0\nFUNCTIONAL_TEST_PASS demo_smoke\n'
           '[SCOREBOARD_SUMMARY] comparisons=0\n')
    monkeypatch.setattr(simulator, 'compile_project', lambda manifest, timeout: dict(status='PASS', binary='xezim', uvm='/uvm/uvm_pkg.sv'))
    monkeypatch.setattr(simulator.subprocess, 'run', lambda cmd, **kw: simulator.subprocess.CompletedProcess(cmd, 0, log, ''))
    outcome = simulator.run_project(result, regress=True, timeout=5)
    # No coverage artifact and zero scoreboard comparisons: fatal for a functional test, expected for a demo.
    assert outcome['tests'][0]['status'] == 'PASS' and outcome['status'] == 'PASS'
    functional = dict(result, demo=False)
    blocked = simulator.run_project(functional, regress=True, timeout=5)
    assert blocked['tests'][0]['status'] == 'BLOCKED'  # the same log is refused when the contract is not a demo


def test_repl_code_demo_builds_the_demo_without_the_normal_notice(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    out = tmp_path / 'run'
    (out / 'dv').mkdir(parents=True)
    (out / 'dv' / 'testplan_doc.json').write_text('{"sections": []}')
    monkeypatch.setattr(terminal, '_default_out', lambda: out)
    seen = []
    monkeypatch.setattr(terminal, 'build_code', lambda directory, variables, **kw: seen.append(variables.get('code_demo')) or
                        dict(demo=True, code_dir='code', tests=[dict(name='demo_smoke')]))
    lines = iter(['/code demo'])
    shown = []
    terminal.repl(input_fn=lambda _p: next(lines, None) or (_ for _ in ()).throw(EOFError), output_fn=shown.append, llm_mode='off')
    text = '\n'.join(shown)
    assert seen == [True] and '--- demo testbench ---' in text and 'before code generation' not in text
    assert 'Demo testbench: code' in text and 'Nothing about the DUT' in text


def test_a_blocked_code_run_points_to_the_demo(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    out = tmp_path / 'run'
    (out / 'dv').mkdir(parents=True)
    (out / 'dv' / 'testplan_doc.json').write_text('{"sections": []}')
    monkeypatch.setattr(terminal, '_default_out', lambda: out)
    monkeypatch.setattr(terminal, 'build_code', lambda *a, **k: (_ for _ in ()).throw(ValueError('Fact quote must occur in a retrieved source excerpt')))
    lines = iter(['/code'])
    shown = []
    terminal.repl(input_fn=lambda _p: next(lines, None) or (_ for _ in ()).throw(EOFError), output_fn=shown.append, llm_mode='off')
    assert 'type /code demo' in '\n'.join(shown)


def test_real_uart_demo_simulation_opt_in(tmp_path, monkeypatch):
    import os
    if os.getenv('DV_AGENT_TEST_SIMULATION') != '1':
        pytest.skip('Set DV_AGENT_TEST_SIMULATION=1 for real Xezim/UVM integration')
    from codegen_uart_fixture import create
    from dv_agent.codegen.simulator import discover, run_project
    if not os.getenv('XEZIM_UVM_DIR'):
        monkeypatch.setenv('XEZIM_UVM_DIR', str(Path(__file__).resolve().parents[1] / '.deps/uvm-core-2020.3.1/src'))
    if discover()['status'] != 'PASS':
        pytest.fail(str(discover()))
    repo = create(tmp_path)
    manifest = build_demo(tmp_path / 'testplan.json', tmp_path / 'interface.json', tmp_path / 'output',
                          rtl_files=list((repo / 'rtl/verilog').glob('*.v')), compile=True)
    assert manifest['compile']['status'] == 'PASS', manifest['compile']
    result = run_project(manifest, regress=True, timeout=120)
    assert result['status'] == 'PASS', [(t['name'], t['reason']) for t in result['tests']]


def with_two_interfaces(spec, definition):
    """The plan's clock/reset groups plus a wide bus (7 ports) listed before a narrow one (1 output)."""
    spec = json.loads(json.dumps(spec))
    quote = 'Acknowledge completes a transfer'
    directions = {p['name']: p['direction'] for p in definition['ports']}
    widths = {p['name']: p['width'] for p in definition['ports']}
    evidence = dict(provenance='DOCUMENTED', quote=quote, cited_chunk_ids=['CH-spec'], inference_reason='')

    def group(name, names):
        return dict(name=name, category='bus', function='Transfers', cited_chunk_ids=['CH-spec'], property_evidence=dict(function=evidence),
                    signals=[dict(name=n, direction=directions[n], width=widths[n], width_documented=True, direction_documented=True,
                                  active_level='high', active_level_documented=True, quote=quote, chunk_id='CH-spec') for n in names])
    spec['interfaces']['groups'] += [group('wide', ['index', 'push', 'pull', 'lanes', 'writing', 'request', 'cycle']), group('narrow', ['ready'])]
    return spec


def test_only_the_requested_number_of_interfaces_are_built_smallest_first_and_the_rest_are_pending(inputs):
    root, spec, definition, _, _ = inputs
    spec = with_two_interfaces(spec, definition)
    sources = {'CH-spec': spec['evidence_index']['CH-spec']['excerpt']}
    pending = []
    contract = build_demo_contract(spec, definition, sources, top='peripheral', limit=1, pending=pending)
    plan = CodePlan.model_validate(contract)
    # 'narrow' is one output, so it cannot drive the DUT; the next smallest interface is added so the simulation has stimulus.
    assert [a.id for a in plan.agents] == ['demo_narrow', 'demo_wide']
    assert pending == []  # nothing is left over, so nothing is pending
    both = build_demo_contract(spec, definition, sources, top='peripheral', limit=2, pending=pending)
    assert [a['id'] for a in both['agents']] == ['demo_narrow', 'demo_wide'] and not both['tie_offs']


def test_deferred_interface_inputs_are_held_at_zero_with_outputs_open_and_listed_at_the_end(inputs):
    root, spec, definition, _, _ = inputs
    spec = with_two_interfaces(spec, definition)
    sources = {'CH-spec': spec['evidence_index']['CH-spec']['excerpt']}
    # Split the wide bus so that one part is deferred.
    wide = next(g for g in spec['interfaces']['groups'] if g['name'] == 'wide')
    wide['signals'], rest = wide['signals'][:3], wide['signals'][3:]
    spec['interfaces']['groups'].append(dict(wide, name='later', signals=rest))
    pending = []
    contract = build_demo_contract(spec, definition, sources, top='peripheral', limit=2, pending=pending)
    plan = CodePlan.model_validate(contract)
    assert len(plan.agents) == 2 and pending
    deferred = {p['interface']: p for p in pending}
    assert set(deferred) <= {'wide', 'later'}
    tied = {t.signal for t in plan.tie_offs}
    for item in pending:
        assert tied >= set(item['inputs_held_at_zero']) and not tied & set(item['outputs_left_open'])
    owned = {n for a in plan.agents for n in a.bindings.values()} | tied
    assert {p['name'] for p in definition['ports'] if p['direction'] == 'input'} - {'tick', 'clear'} <= owned  # every input has an owner
    assert any(q.startswith('PENDING, not built in this prototype:') for q in contract['questions'])


def test_build_demo_records_the_pending_interfaces_and_the_testbench_still_renders(inputs):
    root, spec, definition, _, rtl = inputs
    (root / 'plan.json').write_text(json.dumps(with_two_interfaces(spec, definition)))
    result = build_demo(root / 'plan.json', root / 'interface.json', root / 'output', rtl_files=[rtl], expected_top='peripheral', max_interfaces=2)
    assert result['demo'] is True and result['status'] == 'BUILT_NEEDS_REVIEW'
    record = json.loads((root / 'output/demo_pending.json').read_text())
    assert record['pending_interfaces'] == result['pending_interfaces']
    top = (Path(result['code_dir']) / 'verification_top.sv').read_text()
    assert 'dut_request' in top


def test_real_uart_prototype_with_two_interfaces_simulates_while_the_rest_are_pending(tmp_path, monkeypatch):
    """The point of the limit: a bus that is not built yet must not stop a running simulation."""
    import os
    if os.getenv('DV_AGENT_TEST_SIMULATION') != '1':
        pytest.skip('Set DV_AGENT_TEST_SIMULATION=1 for real Xezim/UVM integration')
    from codegen_uart_fixture import create
    from dv_agent.codegen.simulator import discover, run_project
    if not os.getenv('XEZIM_UVM_DIR'):
        monkeypatch.setenv('XEZIM_UVM_DIR', str(Path(__file__).resolve().parents[1] / '.deps/uvm-core-2020.3.1/src'))
    if discover()['status'] != 'PASS':
        pytest.fail(str(discover()))
    repo = create(tmp_path)
    plan = json.loads((tmp_path / 'testplan.json').read_text())
    definition = json.loads((tmp_path / 'interface.json').read_text())
    directions = {p['name']: p['direction'] for p in definition['ports']}
    quote = next(iter(plan['evidence_index'].values()))['excerpt'][:40]
    chunk = next(iter(plan['evidence_index']))

    def group(name, names):
        return dict(name=name, category='bus', function='Transfers', cited_chunk_ids=[chunk],
                    signals=[dict(name=n, direction=directions[n], quote=quote, chunk_id=chunk) for n in names])
    plan['interfaces']['groups'] = [group('irq', ['int_o']), group('serial', ['stx_pad_o', 'srx_pad_i']),
                                    group('bus', [n for n in directions if n.startswith('wb_') and n not in ('wb_clk_i', 'wb_rst_i')])]
    # The grouped plan only decides which interfaces are built; compiling uses the fixture's own plan, whose port comparison passes.
    from dv_agent.codegen import build_project
    from dv_agent.codegen.build import load_sources
    pending = []
    contract = build_demo_contract(plan, definition, load_sources(plan, tmp_path / 'graph.json'), top=None, directory=tmp_path / 'output',
                                   limit=2, pending=pending)
    (tmp_path / 'output').mkdir(exist_ok=True)
    (tmp_path / 'output/demo_contract.json').write_text(json.dumps(contract))
    assert [p['interface'] for p in pending] == ['misc', 'bus'] and [a['id'] for a in contract['agents']] == ['demo_irq', 'demo_serial']
    assert {t['signal'] for t in contract['tie_offs']} >= {'wb_adr_i', 'wb_stb_i', 'cts_pad_i'} and not {'srx_pad_i'} & {t['signal'] for t in contract['tie_offs']}
    manifest = build_project(tmp_path / 'testplan.json', tmp_path / 'interface.json', tmp_path / 'output',
                             contract_path=tmp_path / 'output/demo_contract.json', rtl_files=list((repo / 'rtl/verilog').glob('*.v')), compile=True)
    top = (Path(manifest['code_dir']) / 'verification_top.sv').read_text()
    assert 'assign dut_wb_adr_i=' in top and 'assign dut_cts_pad_i=' in top and 'assign dut_srx_pad_i=' not in top  # deferred inputs are held
    assert manifest['compile']['status'] == 'PASS', manifest['compile']
    result = run_project(manifest, regress=True, timeout=120)
    assert result['status'] == 'PASS', [(t['name'], t['reason']) for t in result['tests']]


def test_repl_code_demo_takes_an_interface_count_and_lists_pending_interfaces_at_the_end(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    out = tmp_path / 'run'
    (out / 'dv').mkdir(parents=True)
    (out / 'dv' / 'testplan_doc.json').write_text('{"sections": []}')
    monkeypatch.setattr(terminal, '_default_out', lambda: out)
    limits = []
    pending = [dict(interface='bus', ports=['a', 'b', 'c'], inputs_held_at_zero=['a'], outputs_left_open=['b', 'c'])]
    monkeypatch.setattr(terminal, 'build_code', lambda directory, variables, **kw: limits.append(variables.get('code_demo_limit')) or
                        dict(demo=True, code_dir='code', tests=[dict(name='demo_smoke')], pending_interfaces=pending))
    commands = iter(['/code demo', '/code demo 1', '/code demo all'])
    shown = []
    terminal.repl(input_fn=lambda _p: next(commands, None) or (_ for _ in ()).throw(EOFError), output_fn=shown.append, llm_mode='off')
    assert limits == [2, 1, None]  # default two interfaces; "all" means no limit
    text = '\n'.join(shown)
    assert text.count('Pending (not in this prototype; inputs held at 0, outputs open):') == 3 and '  - bus (3 ports)' in text
    assert text.rindex('  - bus (3 ports)') < text.rindex('type /code to build everything')  # the pointer comes last
