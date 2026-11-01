"""Quick testing: a collateral question is asked once, then settled; earlier answers do not pile up as evidence."""
import json

from dv_agent.core.llm import FakeLLM
from dv_agent.quality.human_review import ReviewClient, review_handler
from dv_agent.quality.quick_testing import ENV
from test_codegen import inputs, workflow_model  # noqa: F401  (fixture)


def quick_run(root, plan, monkeypatch):
    """The isolated quick-testing layout: <run>/quick_testing.json beside <run>/dv/testplan_doc.json."""
    monkeypatch.setenv(ENV, '1')
    monkeypatch.setenv('DV_HITL_DEMO_PAUSE_SECONDS', '0')
    run = root/'run'
    (run/'dv').mkdir(parents=True)
    (run/'quick_testing.json').write_text(json.dumps(dict(test_only=True)))
    plan['sections'][0].update(generator='entries', heading='Checks', status='PASS')  # renderable, as a saved plan is
    plan['sections'][0]['entries'][0].update(kind='check', id='storage_check', validation=[], cited_req_ids=[])
    plan_path = run/'dv/testplan_doc.json'
    plan_path.write_text(json.dumps(dict(plan, test_only=True)))
    return run, plan_path


def test_a_repeated_collateral_question_is_answered_once_and_the_build_completes(inputs, monkeypatch):
    from dv_agent.codegen import build_project
    root, plan, definition, contract, rtl = inputs
    run, plan_path = quick_run(root, plan, monkeypatch)
    facts = contract['facts']
    collateral = []

    def infrastructure(payload):
        if payload['task']['id'].startswith('collateral_'):
            collateral.append(payload)
            ambiguities = [dict(kind='interface_roles', question='Which port acknowledges a transfer?')]
        else:
            ambiguities = []
        return dict(understanding='Identify infrastructure', actions=['Bind scoped ports'], completion=['Ports validate'],
                    facts=facts, questions=[], ambiguities=ambiguities)
    llm = workflow_model(contract, code_infrastructure=infrastructure)
    answers = []

    def evaluate(payload):
        answers.append(payload['unit'])
        return dict(bindings_json=json.dumps({'roles': {'ack': 'ready'}}), reason='Provisional choice for testing.',
                    reply='I would use ready as the acknowledge.', assumptions=['Guessed from the port name.'])
    with review_handler(ReviewClient(llm=FakeLLM({'quick_testing_auto_approval': evaluate}), show=lambda x: None, interactive=False)):
        result = build_project(plan_path, root/'interface.json', run, llm=llm, rtl_files=[rtl], compile=False)
    assert result['contract'] == 'verification_codegen_v1'
    assert answers == ['collateral_control']  # asked once; the next round settles it as an assumption
    assert len(collateral) == 2
    quick = [i for i in collateral[-1]['evidence']['documented_items'] if any(s.startswith('QUICK-TEST') for s in i['source_ids'])]
    assert len(quick) <= 1
    pseudo = json.loads(next((run/'code_work').glob('*/collateral_control.pseudocode.json')).read_text())
    assert any(q.startswith('Quick-test assumption, not asked again:') for q in pseudo['questions'])


def test_only_the_latest_quick_test_answer_enters_the_collateral_evidence(inputs, monkeypatch):
    from dv_agent.codegen import build_project
    from dv_agent.plan.approved_clarifications import apply_approval
    from dv_agent.quality.human_review import request_review
    root, plan, definition, contract, rtl = inputs
    run, plan_path = quick_run(root, plan, monkeypatch)
    facts = contract['facts']
    rounds = iter([{'roles': {'ack': 'ready'}}, {'roles': {'stb': 'request'}}])

    def evaluate(payload):
        return dict(bindings_json=json.dumps(next(rounds)), reason='Provisional choice for testing.',
                    reply='I would set it this way.', assumptions=['Guessed.'])
    approved = []
    with review_handler(ReviewClient(llm=FakeLLM({'quick_testing_auto_approval': evaluate}), show=lambda x: None, interactive=False)):
        for question in ('Which port acknowledges?', 'Which port strobes?'):  # two earlier rounds for the same unit
            request, receipt = request_review(run, json.loads(plan_path.read_text()), definition, 'collateral_control', [question], {})
            apply_approval(plan_path, request, receipt)
            approved.append('QUICK-TEST-' + request['id'])
    collateral = []

    def infrastructure(payload):
        if payload['task']['id'].startswith('collateral_'): collateral.append(payload)
        return dict(understanding='Identify infrastructure', actions=['Bind scoped ports'], completion=['Ports validate'],
                    facts=facts, questions=[], ambiguities=[])
    llm = workflow_model(contract, code_infrastructure=infrastructure)
    build_project(plan_path, root/'interface.json', run, llm=llm, rtl_files=[rtl], compile=False)
    quick = {s for i in collateral[-1]['evidence']['documented_items'] for s in i['source_ids'] if s.startswith('QUICK-TEST')}
    assert quick == {approved[-1]}  # the superseded answer is neither pinned nor retrieved
    assert not any(w['source_id'] == approved[0] for w in collateral[-1]['evidence']['source_excerpts'])
    assert collateral[-1]['approved_bindings']['roles'] == {'stb': 'request'}  # later decisions win
