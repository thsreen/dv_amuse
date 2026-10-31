import json

import pytest

from dv_agent.codegen.port_comparison import enforce,condition_supported
from dv_agent.core.llm import FakeLLM
from dv_agent.quality.human_review import (HumanReviewPending,PlanUpdated,ReviewClient,review_handler)
from dv_agent.quality.quick_testing import ENV,prepare_run
from test_codegen import inputs


def seed(tmp_path):
    out=tmp_path/'run';(out/'dv').mkdir(parents=True);(out/'rtl').mkdir()
    signals=[dict(name='TIMEBASE',width='1',direction='input',quote='TIMEBASE 1 Input drives timing',chunk_id='CH-time'),
             dict(name='ADDRESS',width='4 or 8',direction='input',quote='ADDRESS 4 or 8 Input',chunk_id='CH-bus'),
             dict(name='PAYLOAD',width='24 or 48',direction='input',quote='PAYLOAD 24 or 48 Input',chunk_id='CH-bus'),
             dict(name='TRACE',width='1',direction='output',chunk_id='CH-trace',availability='Enabled if TRACE_ENABLE is defined',
                  quote='TRACE is optional. It is enabled if TRACE_ENABLE\nis defined',documented={'availability':False})]
    plan=dict(interfaces=dict(status='PASS',signals=signals),sections=[dict(id='notes',heading='Notes',generator='entries',status='PASS',entries=[])])
    rtl=dict(sources=['selected_top.sv'],ports=[dict(name='timing_pad',width=1,direction='input'),
        dict(name='address_pad',width=8,direction='input'),dict(name='payload',width=48,direction='input')])
    (out/'dv/testplan_doc.json').write_text(json.dumps(plan));(out/'rtl/interface_definition.json').write_text(json.dumps(rtl))
    return out,plan,rtl


def evaluator():
    def respond(p):
        bindings=p['alignment_context']['proposed_bindings']
        return dict(bindings_json=json.dumps(bindings),reason='Selected explicit physical widths and test-only aliases.',
                    assumptions=['Aliases and disabled optional configuration are inferred for this isolated test.'])
    return FakeLLM({'quick_testing_auto_approval':respond})


def test_normal_mode_queues_precise_review_instead_of_hard_failure(tmp_path):
    out,plan,rtl=seed(tmp_path)
    with pytest.raises(HumanReviewPending): enforce(plan,rtl,out)
    request=json.loads(next(out.glob('human_review/*/request.json')).read_text())
    assert request['unit']=='interface_port_alignment'
    assert request['alignment_context']['proposed_bindings']['width_choices']=={'ADDRESS':8,'PAYLOAD':48}
    assert 'TIMEBASE' in request['review_brief']['question'] and 'TRACE' in request['review_brief']['question']
    assert 'CH-trace' in [s['id'] for s in request['review_brief']['sources']]
    assert not list(out.glob('human_review/*/approval.json'))


def test_quick_review_revises_plan_and_revalidates_without_repeating_and_recovers(tmp_path,monkeypatch):
    original,_,rtl=seed(tmp_path);before=(original/'dv/testplan_doc.json').read_text()
    monkeypatch.setenv(ENV,'1');monkeypatch.setenv('DV_HITL_DEMO_PAUSE_SECONDS','0')
    out=prepare_run(original);path=out/'dv/testplan_doc.json';plan=json.loads(path.read_text());llm=evaluator()
    with review_handler(ReviewClient(llm=llm,show=lambda s:None,interactive=False)):
        with pytest.raises(PlanUpdated): enforce(plan,rtl,out)
        revised=json.loads(path.read_text())
        report=enforce(revised,rtl,out)
        assert report['status']==report['independent_validation']['status']=='PASS'
        assert report['review_decisions']['test_only']
        assert report['review_decisions']['review_status']=='TEST_AUTO_APPROVED'
        assert revised['quick_test_approvals'][0]['unit']=='interface_port_alignment'
        assert revised['sections'][-1]['entries'][0]['provenance']=='INFERRED'
        assert revised['interfaces']==plan['interfaces']
        (out/'interface_port_mapping.json').unlink()
        assert enforce(revised,rtl,out)['status']=='PASS'
        assert len(llm.calls)==1
    assert (original/'dv/testplan_doc.json').read_text()==before
    assert (out/'interface_port_validation.md').exists()
    for suffix in ('md','html'): assert 'NOT human approval' in path.with_suffix('.'+suffix).read_text()
    monkeypatch.setenv(ENV,'0')
    with pytest.raises(ValueError,match='Test-only port alignment'): enforce(revised,rtl,out)


def test_real_mismatch_cannot_enter_approval_channel(tmp_path):
    out,plan,rtl=seed(tmp_path)
    rtl['ports'][2]['width']=99
    with pytest.raises(ValueError,match='port comparison BLOCKED'): enforce(plan,rtl,out)
    assert not list(out.glob('human_review/*/request.json'))


def test_invalid_quick_proposal_remains_pending_with_validation_reason(tmp_path,monkeypatch):
    source,_,rtl=seed(tmp_path);monkeypatch.setenv(ENV,'1');monkeypatch.setenv('DV_HITL_DEMO_PAUSE_SECONDS','0')
    out=prepare_run(source);plan=json.loads((out/'dv/testplan_doc.json').read_text())
    llm=FakeLLM({'quick_testing_auto_approval':lambda p:dict(bindings_json=json.dumps({'mappings':{'TIMEBASE':'invented'}}),reason='Bad choice',assumptions=[])})
    with review_handler(ReviewClient(llm=llm,show=lambda s:None)):
        with pytest.raises(HumanReviewPending): enforce(plan,rtl,out)
    assert not list(out.glob('human_review/*/approval.json'))
    assert 'independently validate' in json.loads(next(out.glob('human_review/*/auto_evaluation.json')).read_text())['validation_error']


def test_human_natural_language_confirmation_revises_plan(tmp_path):
    from dv_agent.quality.human_dialogue import respond
    out,plan,rtl=seed(tmp_path)
    reply='Use timing_pad for TIMEBASE and address_pad for ADDRESS with address width 8, payload width 48, and disable the optional trace port.'
    def human(folder,request):
        bindings=request['alignment_context']['proposed_bindings']
        llm=FakeLLM({'human_reply_interpretation':lambda p:dict(bindings_json=json.dumps(bindings),supporting_quote=reply,clarification='')})
        assert 'confirm my understanding' in respond(folder,request,reply,actor='designer',channel='terminal',reference='reply1',llm=llm)
        assert not (folder/'approval.json').exists()
        assert 'Human approval recorded' in respond(folder,request,'yes, approve',actor='designer',channel='terminal',reference='reply2',llm=llm)
    with review_handler(human):
        with pytest.raises(PlanUpdated): enforce(plan,rtl,out)
    revised=json.loads((out/'dv/testplan_doc.json').read_text())
    assert enforce(revised,rtl,out)['status']=='PASS'
    assert revised['human_approvals'][0]['bindings']['mappings']['TIMEBASE']=='timing_pad'
    assert 'Approved by user designer' in revised['sections'][-1]['entries'][0]['comments']


def test_condition_normalization_does_not_accept_negation():
    signal=dict(availability='Enabled if FEATURE_X is defined',documented={'availability':False},
                quote='It is not enabled if FEATURE_X is defined')
    assert not condition_supported(signal)


def test_changed_rtl_configuration_requests_new_review_and_preserves_old_decision(tmp_path,monkeypatch):
    source,_,rtl=seed(tmp_path);monkeypatch.setenv(ENV,'1');monkeypatch.setenv('DV_HITL_DEMO_PAUSE_SECONDS','0')
    out=prepare_run(source);path=out/'dv/testplan_doc.json';llm=evaluator()
    with review_handler(ReviewClient(llm=llm,show=lambda s:None)):
        with pytest.raises(PlanUpdated): enforce(json.loads(path.read_text()),rtl,out)
        old=json.loads((out/'interface_port_mapping.json').read_text())
        rtl['ports'][2]['width']=24
        with pytest.raises(PlanUpdated): enforce(json.loads(path.read_text()),rtl,out)
        report=enforce(json.loads(path.read_text()),rtl,out)
    assert report['status']=='PASS' and report['review_decisions']['width_choices']['PAYLOAD']==24
    assert report['review_decisions']['request_id']!=old['request_id']
    assert len(llm.calls)==2 and list((out/'port_mapping_history').glob('*.json'))


def test_public_build_restarts_after_alignment_review_and_publishes_correct_status(tmp_path,monkeypatch,inputs):
    from dv_agent.codegen import build_project
    root,plan,rtl,_,source=inputs
    plan['interfaces']['signals'][0]['name']='PRIMARY_TIMEBASE'
    plan['interfaces']['groups'][0]['signals'][0]['name']='PRIMARY_TIMEBASE'
    for section in plan['sections']:
        section.update(generator='entries',heading=section['id'],status='PASS')
        for entry in section['entries']: entry.update(kind='check',cited_req_ids=[],validation=[])
    saved=root/'saved';(saved/'dv').mkdir(parents=True);(saved/'rtl').mkdir()
    (saved/'dv/testplan_doc.json').write_text(json.dumps(plan))
    (saved/'rtl/interface_definition.json').write_text(json.dumps(rtl))
    monkeypatch.setenv(ENV,'1');monkeypatch.setenv('DV_HITL_DEMO_PAUSE_SECONDS','0')
    out=prepare_run(saved)
    with review_handler(ReviewClient(llm=evaluator(),show=lambda s:None)):
        result=build_project(out/'dv/testplan_doc.json',out/'rtl/interface_definition.json',out,
                             contract_path=root/'contract.json',rtl_files=[source],compile=False)
    assert result['interface_port_comparison']['independent_validation']['status']=='PASS'
    assert json.loads((out/'code_generation_state.json').read_text())['status']=='BUILT_NEEDS_REVIEW'
    assert result['test_only']
