"""Quick testing defers checks/coverage that name a nonexistent agent (the clock and reset are not agents)."""
import json

import pytest

from dv_agent.codegen.defer_unsupported import defer_unknown_agents
from dv_agent.codegen.workplan import Fragment, restore_maps  # noqa: F401
from dv_agent.codegen.validate import validate
from test_codegen import inputs, workflow_model  # noqa: F401  (fixture)

FACT = 'behavior'


def fragment(**kw):
    base = dict(sequencer_variables=[], registers=[], facts=[], sequences=[], routes=[], checks=[], hooks=[], coverage=[],
                step_implementations=[], questions=[])
    return Fragment.model_validate(base | kw)


def test_items_naming_a_missing_agent_are_dropped_and_their_steps_become_questions():
    f = fragment(
        checks=[dict(id='ok_check', agent='control', kind='known_controls', fact_ids=[FACT]),
                dict(id='bad_check', agent='clock_agent', kind='known_controls', fact_ids=[FACT])],
        coverage=[dict(id='bad_cov', agent='clock_agent', crosses=[], sample_address=None, sample_kinds=[], fact_ids=[FACT],
                       points=[dict(name='p', field='data', mask=0, shift=0, bins=[dict(name='b', values=[0])])])],
        step_implementations=[dict(step='check_steps/0', component_ids=['ok_check'], question=''),
                              dict(step='check_steps/1', component_ids=['bad_check'], question=''),
                              dict(step='coverage_steps/0', component_ids=['bad_cov'], question='')])
    dropped = defer_unknown_agents(f, ['control'])
    assert set(dropped) == {'bad_check', 'bad_cov'} and [c.id for c in f.checks] == ['ok_check'] and f.coverage == []
    by_step = {m.step: m for m in f.step_implementations}
    assert by_step['check_steps/0'].component_ids == ['ok_check'] and not by_step['check_steps/0'].question
    assert by_step['check_steps/1'].component_ids == [] and by_step['check_steps/1'].question.startswith('Deferred:')
    assert by_step['coverage_steps/0'].question and any('clock_agent' in q for q in f.questions)


def test_a_fragment_that_only_uses_existing_agents_is_untouched():
    f = fragment(checks=[dict(id='c', agent='control', kind='known_controls', fact_ids=[FACT])])
    assert defer_unknown_agents(f, ['control']) == {} and len(f.checks) == 1 and f.questions == []


def test_the_validation_message_names_every_offender_and_the_valid_agents(inputs):
    root, spec, definition, contract, _ = inputs
    from dv_agent.codegen.contracts import CodePlan
    bad = json.loads(json.dumps(contract))
    bad['checks'] = [dict(id='x', agent='clock_agent', kind='known_controls', fact_ids=[FACT])]
    plan = CodePlan.model_validate(bad)
    try:
        validate(plan, spec, definition, {'CH-spec': spec['evidence_index']['CH-spec']['excerpt']})
    except ValueError as exc:
        text = str(exc)
        assert 'x (agent clock_agent)' in text and "Bus agents: ['control']" in text and 'common UVCs, not agents' in text
    else:
        raise AssertionError('expected a validation error')


def clock_coverage_feature(contract):
    """A feature answer whose coverage goal samples a 'clock agent' that the testbench does not have."""
    from test_codegen import workflow_model
    llm = workflow_model(contract)
    normal = llm.handlers['code_feature']

    def feature(payload):
        result = normal(payload)
        result['coverage'] = [dict(id='storage_feature_clk', agent='clock_agent', crosses=[], sample_address=None, sample_kinds=[], fact_ids=['behavior'],
                                   points=[dict(name='period', field='data', mask=0, shift=0, bins=[dict(name='seen', values=[0])])])]
        result['step_implementations'] = [dict(m, component_ids=['storage_feature_clk']) if m['step'].startswith('coverage_steps') else m
                                          for m in result['step_implementations']]
        return result
    llm.handlers['code_feature'] = feature
    return llm


def test_quick_testing_builds_around_a_clock_agent_that_does_not_exist(inputs, monkeypatch):
    from dv_agent.codegen import build_project
    from test_quick_testing_rounds import quick_run
    root, plan, definition, contract, rtl = inputs
    run, plan_path = quick_run(root, plan, monkeypatch)
    result = build_project(plan_path, root / 'interface.json', run, llm=clock_coverage_feature(contract), rtl_files=[rtl], compile=False)
    assert result['contract'] == 'verification_codegen_v1'
    code_plan = json.loads((run / 'code_plan.json').read_text())
    assert not any(c['agent'] == 'clock_agent' for c in code_plan['coverage'])
    assert any('Deferred (quick testing)' in q and 'clock_agent' in q for q in code_plan['questions'])


def test_a_normal_build_still_refuses_it_and_says_which_agents_exist(inputs):
    import pytest
    from dv_agent.codegen import build_project
    root, plan, definition, contract, rtl = inputs
    with pytest.raises(ValueError, match=r"unknown monitor agent: storage_feature_clk \(agent clock_agent\). Agents: \['control'\]"):
        build_project(root / 'plan.json', root / 'interface.json', root / 'output', llm=clock_coverage_feature(contract), rtl_files=[rtl], compile=False)


def test_a_scoreboard_hook_without_a_route_is_deferred_and_one_with_a_route_is_kept():
    f = fragment(
        hooks=[dict(id='compare_fifo', target='top_level_scoreboard', slot='scoreboard.compare', purpose='internal FIFO occupancy', fact_ids=[FACT]),
               dict(id='compare_path', target='transmit_path', slot='scoreboard.compare', purpose='tx path', fact_ids=[FACT])],
        step_implementations=[dict(step='check_steps/0', component_ids=['compare_fifo'], question=''),
                              dict(step='check_steps/1', component_ids=['compare_path'], question='')])
    dropped = defer_unknown_agents(f, ['control'], ['transmit_path'])
    assert list(dropped) == ['compare_fifo'] and [h.id for h in f.hooks] == ['compare_path']
    steps = {m.step: m for m in f.step_implementations}
    assert steps['check_steps/0'].question.startswith('Deferred:') and steps['check_steps/1'].component_ids == ['compare_path']
    assert any('internal state is not observable' in q for q in f.questions)
    untouched = fragment(hooks=[dict(id='h', target='nowhere', slot='scoreboard.compare', purpose='x', fact_ids=[FACT])])
    assert defer_unknown_agents(untouched, ['control']) == {} and len(untouched.hooks) == 1  # routes unknown: nothing is judged


def _rule_check(fragment):
    """Stand-ins for contract rules: every bad_ hook is refused by the same rule; a sequence needs its register."""
    if any(h.id.startswith('bad_') for h in fragment.hooks):
        raise ValueError('Coverage hook requires selected coverage infrastructure')
    if fragment.sequences and not fragment.registers:
        raise ValueError('register_write names a register that is not declared')


def _hook(name):
    return dict(id=name, target='control', slot='coverage.sample', purpose='x', fact_ids=[FACT])


def _sequence():
    return dict(id='seq', agent='control', purpose='p', fact_ids=[FACT], operations=[dict(kind='idle', cycles=1)])


def _register():
    return dict(id='reg', agent='control', address=1, width=8, access='WO', mask=255, fact_ids=[FACT])


def test_several_items_breaking_one_rule_are_all_dropped_and_nothing_innocent_with_them():
    """Run 1305: three hooks broke one rule, so removing any one changed nothing and a search blamed the register."""
    from dv_agent.codegen.defer_unsupported import defer_until_valid
    f = fragment(hooks=[_hook('bad_a'), _hook('bad_b'), _hook('good')], sequences=[_sequence()], registers=[_register()],
                 step_implementations=[dict(step='coverage_steps/0', component_ids=['bad_a', 'good'], question=''),
                                       dict(step='coverage_steps/1', component_ids=['bad_b'], question='')])
    dropped = defer_until_valid(f, _rule_check)
    assert set(dropped) == {'bad_a', 'bad_b'} and 'Coverage hook requires' in dropped['bad_a']
    assert [h.id for h in f.hooks] == ['good'] and [r.id for r in f.registers] == ['reg'] and [s.id for s in f.sequences] == ['seq']
    steps = {m.step: m for m in f.step_implementations}
    assert steps['coverage_steps/0'].component_ids == ['good'] and not steps['coverage_steps/0'].question
    assert steps['coverage_steps/1'].question.startswith('Deferred:') and any('bad_b' in q for q in f.questions)
    _rule_check(f)  # the result is valid


def test_an_item_needing_something_refused_goes_too_and_a_valid_answer_is_untouched():
    from dv_agent.codegen.defer_unsupported import defer_until_valid
    alone = fragment(sequences=[_sequence()])
    assert list(defer_until_valid(alone, _rule_check)) == ['seq'] and alone.sequences == []
    fine = fragment(sequences=[_sequence()], registers=[_register()], hooks=[_hook('good')])
    assert defer_until_valid(fine, _rule_check) == {} and len(fine.hooks) == 1 and fine.questions == []


def test_an_item_depending_on_a_later_one_in_the_same_group_is_kept_on_the_second_pass():
    from dv_agent.codegen.defer_unsupported import defer_until_valid
    def check(f):
        ids = [s.id for s in f.sequences]
        if 'child' in ids and 'base' not in ids:
            raise ValueError('Unknown base sequence')
        if 'wrong' in ids:
            raise ValueError('Sequence needs an active agent')
    f = fragment(sequences=[dict(_sequence(), id='child'), dict(_sequence(), id='base'), dict(_sequence(), id='wrong')])
    assert list(defer_until_valid(f, check)) == ['wrong'] and {s.id for s in f.sequences} == {'child', 'base'}


def test_a_contract_invalid_without_the_answer_is_left_for_the_normal_check():
    from dv_agent.codegen.defer_unsupported import defer_until_valid
    def broken(f):
        raise ValueError('The foundation itself is invalid')
    f = fragment(hooks=[_hook('good')])
    assert defer_until_valid(f, broken) == {} and len(f.hooks) == 1


def wrong_hook_feature(contract):
    llm = workflow_model(contract)
    normal = llm.handlers['code_feature']

    def feature(payload):
        return dict(normal(payload), hooks=[dict(id='storage_feature_hook', target='nowhere', slot='driver.body', purpose='x', fact_ids=['behavior'])])
    llm.handlers['code_feature'] = feature
    return llm


def test_quick_testing_defers_any_item_the_contract_refuses_and_a_normal_build_still_refuses(inputs, monkeypatch):
    from dv_agent.codegen import build_project
    from test_quick_testing_rounds import quick_run
    root, plan, definition, contract, rtl = inputs
    with pytest.raises(ValueError, match='Agent hook requires an agent target'):
        build_project(root / 'plan.json', root / 'interface.json', root / 'normal', llm=wrong_hook_feature(contract), rtl_files=[rtl], compile=False)
    run, plan_path = quick_run(root, plan, monkeypatch)
    result = build_project(plan_path, root / 'interface.json', run, llm=wrong_hook_feature(contract), rtl_files=[rtl], compile=False)
    assert result['contract'] == 'verification_codegen_v1'
    built = json.loads((run / 'code_plan.json').read_text())
    assert built['hooks'] == [] and any('storage_feature_hook' in q and 'Agent hook requires' in q for q in built['questions'])


def test_a_feature_with_deferrals_passes_once_two_items_are_complete():
    from dv_agent.codegen.defer_unsupported import complete_items, feature_status
    assert feature_status(['x'], 2) == 'PASS' and feature_status(['x'], 3) == 'PASS'
    assert feature_status(['x'], 1) == 'DEFERRED' and feature_status(['x'], 0) == 'DEFERRED'
    assert feature_status([], 0) == 'PASS' and feature_status(None, 1) == 'PASS'  # nothing was dropped
    assert complete_items(fragment(hooks=[_hook('good')], sequences=[_sequence()], registers=[_register()])) == 2  # a register supports, it is not a check


def _feature_llm(contract, feature):
    llm = workflow_model(contract)
    llm.handlers['code_feature'] = feature
    return llm


def test_quick_testing_lists_a_feature_it_cannot_complete_and_carries_on(inputs, monkeypatch):
    from dv_agent.codegen.workplan import design
    from test_quick_testing_rounds import quick_run
    root, plan, definition, contract, rtl = inputs
    plan['sections'][0]['entries'].append(dict(plan['sections'][0]['entries'][0]))
    run, plan_path = quick_run(root, plan, monkeypatch)
    llm = workflow_model(contract)
    normal = llm.handlers['code_feature']
    llm.handlers['code_feature'] = lambda p: dict(normal(p), step_implementations=[]) if p['task_id'] == 'broken_feature' else normal(p)
    task = lambda name, entry: dict(id=name, title=name, category='feature', goal='Read/write storage control', plan_pointers=[f'/sections/0/entries/{entry}'],
                                    depends_on=[], queries=['control storage register clock reset bus'])
    llm.handlers['code_grouping'] = lambda p: dict(understanding='Two features', tasks=[task('broken_feature', 0), task('storage_feature', 1)], questions=[])
    llm.handlers['code_collation'] = lambda p: dict(shared_setup=['Reuse the shared bus'], execution_order=[list(p['features'])], stimulus_approach=['Sequence'],
                                                    check_approach=['Compare'], coverage_approach=['Monitor'], questions=[])
    built = design(llm, json.loads(plan_path.read_text()), definition, {'CH-spec': plan['evidence_index']['CH-spec']['excerpt']}, run)
    manifest = json.loads((run / 'code_work_manifest.json').read_text())
    assert manifest['status'] == 'COMPLETE_NEEDS_REVIEW' and manifest['features']['deferred'] == ['broken_feature'] and manifest['features']['passed'] == ['storage_feature']
    assert any(q.startswith('Deferred (quick testing): feature broken_feature was not built') for q in built.questions)
    assert [t.id for t in built.tests] and built.sequences


def test_quick_testing_says_so_when_no_feature_could_be_completed(inputs, monkeypatch):
    from dv_agent.codegen.workplan import design
    from test_quick_testing_rounds import quick_run
    root, plan, definition, contract, rtl = inputs
    run, plan_path = quick_run(root, plan, monkeypatch)
    llm = workflow_model(contract)
    normal = llm.handlers['code_feature']
    llm.handlers['code_feature'] = lambda p: dict(normal(p), step_implementations=[])
    with pytest.raises(ValueError, match='No feature could be completed'):
        design(llm, json.loads(plan_path.read_text()), definition, {'CH-spec': plan['evidence_index']['CH-spec']['excerpt']}, run)


def test_a_normal_build_still_stops_on_a_feature_it_cannot_complete(inputs):
    from dv_agent.codegen.workplan import design
    root, plan, definition, contract, rtl = inputs
    normal = workflow_model(contract).handlers['code_feature']
    llm = _feature_llm(contract, lambda p: dict(normal(p), step_implementations=[]))
    with pytest.raises(ValueError, match='exactly one implementation mapping'):
        design(llm, plan, definition, {'CH-spec': plan['evidence_index']['CH-spec']['excerpt']}, root / 'output')
