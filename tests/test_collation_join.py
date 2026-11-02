"""Large collated summaries are joined by script, and later stages get a prompt that fits."""
import json
from types import SimpleNamespace

from dv_agent.codegen.render import join_hook_bodies
from dv_agent.codegen.workplan import ImplementationApproach, Pseudocode, _approach_view, _collate, _components_view


def task(*requires):
    return SimpleNamespace(depends_on=[SimpleNamespace(task_id=r) for r in requires])


def pseudo(tid):
    return Pseudocode(understanding=tid, preconditions=[], stimulus_steps=['x' * 20000], check_steps=[], coverage_steps=[],
                      completion=[], facts=[], questions=[], blockers=[])


def large_answers(calls):
    def call(name, data, model, rules, check=lambda r: None):
        calls.append(data)
        ids = list(data['features'])
        answer = ImplementationApproach(execution_order=[[i] for i in ids], shared_setup=[f'setup {ids[0]}'] * 1,
                                        stimulus_approach=[f'{i} ' + 'y' * 20000 for i in ids], check_approach=['check'],
                                        coverage_approach=['cover'], questions=[f'q {ids[0]}'])
        return answer
    return call


def test_summaries_too_large_to_pair_are_joined_without_another_model_call_or_a_lost_step():
    tasks = {'a': task(), 'b': task('a'), 'c': task('b')}
    calls = []
    approach = _collate(large_answers(calls), 'strategy', tasks, {t: pseudo(t) for t in tasks})
    assert len(calls) == 3  # one per feature, none repeated for the summaries
    assert approach.execution_order == [['a'], ['b'], ['c']]
    assert all(any(step.startswith(t + ' ') for step in approach.stimulus_approach) for t in tasks)
    assert approach.questions == ['q a', 'q b', 'q c'] and approach.check_approach == ['check']


def test_a_lone_summary_is_not_sent_back_to_the_model():
    tasks = {'a': task(), 'b': task(), 'c': task()}
    calls = []
    def call(name, data, model, rules, check=lambda r: None):
        calls.append(data)
        ids = list(data['features']) + [i for g in data['collated_groups'] for i in g['feature_ids']]
        size = 14000 if data['level'] == 0 else 10
        return ImplementationApproach(execution_order=[ids], shared_setup=['s' * size], stimulus_approach=['t'], check_approach=['c'],
                                      coverage_approach=['v'], questions=[])
    approach = _collate(call, 'strategy', tasks, {t: pseudo(t) for t in tasks})
    assert sorted(approach.execution_order[0]) == ['a', 'b', 'c']
    assert [len(c['collated_groups']) for c in calls if c['level'] == 1] == [2]  # the third waits for the next level


def test_integration_prompt_views_stay_small_and_keep_the_order_and_item_ids():
    approach = ImplementationApproach(execution_order=[['a'], ['b']], shared_setup=['s' * 5000] * 10, stimulus_approach=['t' * 5000] * 10,
                                      check_approach=['c'], coverage_approach=['v'], questions=['q' * 900] * 20)
    view = _approach_view(approach, budget=10000)
    assert len(json.dumps(view)) < 12000 and view['execution_order'] == [['a'], ['b']] and view['check_approach'] == ['c']
    assert len(approach.shared_setup[0]) == 5000  # the saved approach is untouched
    small = approach.model_copy(update=dict(shared_setup=['s'], stimulus_approach=['t'], questions=[]))
    assert _approach_view(small, budget=10000) == small.model_dump()
    components = _components_view({'a': dict(understanding='u' * 900, completion=['c'] * 50, sequences=['s1'], checks=['k'], routes=[], coverage=[], questions=['q'] * 50)})
    assert components == {'a': dict(understanding='u' * 240, sequences=['s1'], checks=['k'], routes=[], coverage=[])}


def test_several_hooks_on_one_slot_keep_their_own_declarations_and_observers_run_side_by_side():
    assert join_hook_bodies(['int a;'], 'driver.body') == 'int a;'
    assert join_hook_bodies(['int a;', 'int a;'], 'driver.body') == 'begin\nint a;\nend\nbegin\nint a;\nend'
    assert join_hook_bodies(['forever x;', 'forever y;'], 'monitor.body') == 'fork\nbegin\nforever x;\nend\nbegin\nforever y;\nend\njoin'
