"""A refused quick-testing answer gets one repair attempt with the error; every refusal is kept."""
import json

from dv_agent.core.llm import FakeLLM
from dv_agent.quality.quick_testing import ENV, REPAIR_ATTEMPTS, QuickTestApprover, prepare_run
from test_human_review import pending, seed

GOOD = {'reset': 'rst', 'reset_active': 'high'}
BAD = {'reset': 'not_a_port', 'reset_active': 'high'}


def answers(*bindings):
    calls, queue = [], list(bindings)

    def answer(payload):
        calls.append(payload)
        return dict(bindings_json=json.dumps(queue.pop(0)), reason='Provisional choice for testing.',
                    reply='I would use the reset input, active high.', assumptions=['Assumed high.'])
    return FakeLLM({'quick_testing_auto_approval': answer}), calls


def setup(tmp_path, monkeypatch):
    run, plan, definition = seed(tmp_path)
    monkeypatch.setenv(ENV, '1')
    monkeypatch.setenv('DV_HITL_DEMO_PAUSE_SECONDS', '0')
    run = prepare_run(run)
    plan = json.loads((run / 'dv/testplan_doc.json').read_text())
    return pending(run, plan, definition)


def test_a_refused_answer_is_repaired_once_with_the_error_and_the_scoped_ports(tmp_path, monkeypatch):
    folder, request = setup(tmp_path, monkeypatch)
    llm, calls = answers(BAD, GOOD)
    QuickTestApprover(llm, lambda x: None)(folder, request)
    assert len(calls) == 2 and 'previous_answer_refused' not in calls[0]
    refused = calls[1]['previous_answer_refused']
    assert json.loads(refused['bindings_json']) == BAD and refused['error']
    assert refused['scoped_ports'] == [p['name'] if isinstance(p, dict) else p for p in request['ports']]
    receipt = json.loads((folder / 'approval.json').read_text())
    assert receipt['bindings'] == GOOD and receipt['refused_answers'][0]['attempt'] == 1


def test_when_every_attempt_is_refused_nothing_is_approved_and_the_answers_are_kept(tmp_path, monkeypatch):
    folder, request = setup(tmp_path, monkeypatch)
    llm, calls = answers(*([BAD] * REPAIR_ATTEMPTS))
    QuickTestApprover(llm, lambda x: None)(folder, request)
    assert len(calls) == REPAIR_ATTEMPTS and not (folder / 'approval.json').exists()
    result = json.loads((folder / 'auto_evaluation.json').read_text())
    assert result['status'] == 'BLOCKED' and result['validation_error']
    assert [r['attempt'] for r in result['refused_answers']] == list(range(1, REPAIR_ATTEMPTS + 1))
    assert all(json.loads(r['bindings_json']) == BAD for r in result['refused_answers'])


def test_a_group_of_ports_under_one_role_becomes_one_role_per_port(tmp_path, monkeypatch):
    from dv_agent.quality.quick_testing import flatten_roles
    grouped = {'roles': {'driver': ['a_i', 'b_i'], 'ack': ['c_o'], 'sel': 'd_i'}, 'tie_offs': {'a_i': 0}}
    assert flatten_roles(grouped) == {'roles': {'driver_a_i': 'a_i', 'driver_b_i': 'b_i', 'ack': 'c_o', 'sel': 'd_i'}, 'tie_offs': {'a_i': 0}}
    plain = {'reset': 'rst', 'reset_active': 'high'}
    assert flatten_roles(plain) is plain
