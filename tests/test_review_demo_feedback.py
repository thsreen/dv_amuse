import json
from pathlib import Path

import pytest

from dv_agent.quality.quick_testing import QuickTestApprover,ENV,prepare_run
from test_quick_testing import evaluator
from test_human_review import seed,pending


def test_demo_question_response_pause_precede_approval(tmp_path,monkeypatch):
    run,plan,definition=seed(tmp_path);monkeypatch.setenv(ENV,'1')
    run=prepare_run(run);plan=json.loads((run/'dv/testplan_doc.json').read_text())
    folder,request=pending(run,plan,definition)
    monkeypatch.setenv('DV_HITL_DEMO_PAUSE_SECONDS','2')
    shown=[];delays=[]
    def sleep(seconds):
        delays.append(seconds)
        assert any(request['question'] in line for line in shown)
        assert any('Reset asserted level: high' in line for line in shown)
        assert not (folder/'approval.json').exists()
    QuickTestApprover(evaluator(),shown.append,sleep=sleep)(folder,request)
    assert delays==[2] and (folder/'approval.json').exists()
    assert 'Generated response' in (folder/'review_transcript.md').read_text()


def test_demo_interrupt_never_records_approval(tmp_path,monkeypatch):
    run,plan,definition=seed(tmp_path);monkeypatch.setenv(ENV,'1')
    run=prepare_run(run);plan=json.loads((run/'dv/testplan_doc.json').read_text());folder,request=pending(run,plan,definition)
    monkeypatch.setenv('DV_HITL_DEMO_PAUSE_SECONDS','2')
    def stop(seconds): raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt): QuickTestApprover(evaluator(),lambda x:None,sleep=stop)(folder,request)
    assert not (folder/'approval.json').exists()


def test_dashboard_keeps_review_on_screen(tmp_path):
    from orchestrator_agent.tui import Dashboard
    frames=[];dash=Dashboard(tmp_path,frames.append)
    dash.handle(dict(event='review_presentation_start'))
    frames.clear()
    dash.handle(dict(event='task_progress',message='Model evaluating'))
    dash.redraw()
    assert frames==[]
    dash.handle(dict(event='review_presentation_end'))
    assert frames and not dash.review_presenting


def test_feedback_done_requires_ready_section_comment_and_reference(tmp_path):
    from dv_agent.plan.human_feedback import render,apply
    doc=dict(sections=[dict(id='checks',generator='entries',heading='Checks',status='BLOCKED',entries=[])],
             evidence_index={'CH-source':dict(excerpt='Source text')},generation_status='PARTIAL')
    (tmp_path/'testplan_doc.json').write_text(json.dumps(doc))
    file=tmp_path/'edited.md'
    file.write_text(render(doc).replace('| checks | OPEN |  |  | OPEN |','| checks | DONE | Reviewed | CH-source | OPEN |'))
    report=apply(tmp_path,file,'Engineer')
    assert report['status']=='NEEDS_WORK'
    unchanged=json.loads((tmp_path/'testplan_doc.json').read_text())
    assert unchanged['sections'][0]['status']=='BLOCKED' and unchanged['generation_status']=='PARTIAL'
    doc['sections'][0]['status']='PASS';(tmp_path/'testplan_doc.json').write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='Report changed'): apply(tmp_path,file,'Engineer')
    file.write_text(render(doc).replace('| checks | OPEN |  |  | OPEN |','| checks | DONE | Reviewed | CH-source | OPEN |'))
    assert apply(tmp_path,file,'Engineer')['status']=='DONE'
    assert (tmp_path/'feedback_revisions').is_dir()


def test_fixed_uvc_sources_are_outside_templates_and_copied_unchanged():
    from dv_agent.uvc import sources,COMMON_UVCS,UVC_ROOT
    assert 'templates' not in UVC_ROOT.parts
    for kind in COMMON_UVCS:
        assert sources(kind)
        assert all('{{' not in path.read_text() for path in sources(kind))
