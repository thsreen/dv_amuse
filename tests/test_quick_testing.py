"""Quick-testing decisions are isolated, inferred and require explicit startup opt-in."""
import json

import pytest

from dv_agent.core.llm import FakeLLM
from dv_agent.quality.human_review import request_review, review_handler, ReviewClient, validate_receipt
from dv_agent.quality.quick_testing import ENV, prepare_run
from dv_agent.plan.approved_clarifications import apply_approval
from test_human_review import seed


def evaluator(bindings=None):
    return FakeLLM({'quick_testing_auto_approval':lambda p:dict(
        bindings_json=json.dumps(bindings or {'reset':'rst','reset_active':'high'}),
        reason='Use the scoped reset input with a provisional active-high level for testing.',
        assumptions=['Active-high polarity is inferred, not designer validated.'])})


def test_auto_approval_isolated_inferred_audited_and_disabled_outside_mode(tmp_path,monkeypatch):
    source,_,definition=seed(tmp_path)
    original=(source/'dv/testplan_doc.json').read_text()
    monkeypatch.setenv(ENV,'1')
    run=prepare_run(source);path=run/'dv/testplan_doc.json';plan=json.loads(path.read_text())
    with review_handler(ReviewClient(llm=evaluator(),show=lambda x:None,interactive=False)):
        request,receipt=request_review(run,plan,definition,'foundation_reset',['Which input and asserted level?'],{})
    assert receipt['status']=='TEST_AUTO_APPROVED' and receipt['channel']=='quick_testing'
    assert receipt['test_only'] and receipt['assumptions']
    apply_approval(path,request,receipt)
    changed=json.loads(path.read_text());entry=changed['sections'][-1]['entries'][0]
    assert entry['provenance']=='INFERRED' and entry['source_kind']=='QUICK_TEST_AUTO_APPROVAL'
    assert not changed.get('human_approvals')
    assert changed['quick_test_approvals'][0]['bindings']['reset_active']=='high'
    assert (source/'dv/testplan_doc.json').read_text()==original
    for extension in ('md','html'):
        rendered=(run/f'dv/testplan_doc.{extension}').read_text()
        assert 'QUICK TESTING ONLY' in rendered and 'NOT human approval' in rendered
    from dv_agent.codegen.reasoning import eligible_items
    sources={sid:v['excerpt'] for sid,v in changed['evidence_index'].items()}
    assert eligible_items(changed,sources)
    from dv_agent.codegen.contracts import Fact
    from dv_agent.codegen.validate import validate_facts
    item=eligible_items(changed,sources)[0];sid=item['source_ids'][0]
    fact=Fact(id='test_reset',statement='Test-only reset binding',source_id=sid,quote=sources[sid],plan_pointer=item['plan_pointer'])
    validate_facts([fact],changed,sources)
    monkeypatch.setenv(ENV,'0')
    assert not eligible_items(changed,sources)
    with pytest.raises(ValueError,match='not a documented'): validate_facts([fact],changed,sources)
    with pytest.raises(ValueError,match='Invalid or stale'): validate_receipt(request,receipt)
    from dv_agent.codegen.build import build_project
    with pytest.raises(ValueError,match='Quick-testing plan requires'):
        build_project(path,run/'rtl/interface_definition.json',run,llm=evaluator())


def test_invalid_evaluation_cannot_bypass_port_checks(tmp_path,monkeypatch):
    from dv_agent.quality.human_review import HumanReviewPending
    source,_,definition=seed(tmp_path);monkeypatch.setenv(ENV,'1')
    run=prepare_run(source);plan=json.loads((run/'dv/testplan_doc.json').read_text())
    with review_handler(ReviewClient(llm=evaluator({'reset':'missing_port'}),show=lambda x:None)):
        with pytest.raises(HumanReviewPending):
            request_review(run,plan,definition,'foundation_reset',['Which reset input?'],{})
    assert not list(run.glob('human_review/*/approval.json'))
    assert json.loads(next(run.glob('human_review/*/auto_evaluation.json')).read_text())['status']=='BLOCKED'


def test_startup_option_is_explicit_and_not_sticky(monkeypatch):
    from orchestrator_agent import cli, repl
    modes=[]
    import os
    monkeypatch.setattr(repl,'repl',lambda **kw:modes.append(os.environ.get(ENV)) or 0)
    assert cli.main(['--quick-testing-auto-approve-inferences'])==0
    assert cli.main([])==0
    assert modes==['1','0']


def test_quick_testing_copy_not_selected_as_normal_plan(tmp_path,monkeypatch):
    from test_code_dashboard import saved
    from orchestrator_agent.saved_runs import latest_successful
    source,_=saved(tmp_path/'runs','original')
    path=source/'dv/testplan_doc.json';plan=json.loads(path.read_text())
    plan['sections'][0].update(generator='entries',heading='Stimulus',entries=[])
    path.write_text(json.dumps(plan))
    monkeypatch.setenv(ENV,'1');copy=prepare_run(source)
    assert copy!=source and latest_successful(source.parent)[0]==source


def test_code_after_a_restart_resumes_the_newest_copy_of_the_same_plan(tmp_path,monkeypatch):
    import os
    source,_,_=seed(tmp_path)
    monkeypatch.setenv(ENV,'1')
    first=prepare_run(source)
    assert prepare_run(source)==first  # a new session on the same saved plan keeps its checkpoints
    (first/'llm_cache').mkdir();(first/'llm_cache/kept').write_text('x')
    assert (prepare_run(source)/'llm_cache/kept').is_file()
    plan=source/'dv/testplan_doc.json'
    later=(first/'quick_testing.json').stat().st_mtime+5
    os.utime(plan,(later,later))  # the saved plan changed after the copy was made
    second=prepare_run(source)
    assert second!=first and not (second/'llm_cache').exists()


def test_a_hook_that_stays_invalid_is_left_out_only_in_quick_testing(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from dv_agent.codegen import reasoning
    hook=SimpleNamespace(id='h',slot='driver.body',target='a',fact_ids=[],model_dump=lambda:dict(id='h',slot='driver.body'))
    plan=SimpleNamespace(hooks=[hook],facts=[],agents=[],questions=[],model_dump=lambda:{})
    llm=FakeLLM({'code_hook':lambda p:dict(code='$system("x");')})
    monkeypatch.setenv(ENV,'1')
    with pytest.raises(ValueError,match='allowed system function|forbidden'):
        reasoning.implement(llm,plan,tmp_path)  # a normal run still stops
    (tmp_path/'quick_testing.json').write_text('{}')
    assert reasoning.implement(llm,plan,tmp_path)=={}
    assert plan.questions and plan.questions[0].startswith('Deferred (quick testing): hook h')
