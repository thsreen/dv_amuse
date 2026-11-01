"""Quick testing defers checks/coverage that name a nonexistent agent (the clock and reset are not agents)."""
import json

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
