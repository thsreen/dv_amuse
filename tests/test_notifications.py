"""Notification transport is always mocked; no real bot is contacted by tests."""
import json
import subprocess
from pathlib import Path
import pytest
from types import SimpleNamespace

from dv_agent.core import notifications


@pytest.mark.parametrize('receipt',[
    {'success':True,'skipped':True,'reason':'cron_auto_delivery_duplicate_target'},
    {'success':True}, {'error':'rejected'}, 'sent',
    {'success':True,'message_id':'42','chat_id':'999','platform':'telegram'}])
def test_exit_zero_without_correct_delivery_proof_is_not_sent(monkeypatch,receipt):
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123')
    monkeypatch.setenv('DV_AGENT_NOTIFICATION_TRANSPORT','auto')
    monkeypatch.setattr(notifications.subprocess,'run',lambda *a,**k:SimpleNamespace(
        returncode=0,stdout=json.dumps(receipt) if isinstance(receipt,dict) else receipt,stderr=''))
    monkeypatch.setattr(notifications,'_telegram',lambda *a:pytest.fail('Do not duplicate an uncertain send'))
    result=notifications.send_message('test')
    assert result['status'] in ('DELIVERY_SKIPPED','DELIVERY_UNCERTAIN')


def test_sender_uses_hermes_and_stdin_without_logging_credentials(monkeypatch):
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123')
    calls=[]
    def process(args,**kwargs):
        calls.append((args,kwargs));return SimpleNamespace(returncode=0,stdout=json.dumps(dict(success=True,message_id='42',platform='telegram',chat_id='123')),stderr='')
    monkeypatch.setattr(notifications.subprocess,'run',process)
    result=notifications.send_message('DV run started')
    assert result==dict(status='SENT',transport='hermes/telegram',message_id='42')
    assert calls[0][0][-4:]==['send','--json','--to','telegram:123']
    assert calls[0][1]['input']=='DV run started' and calls[0][1]['timeout']==15
    assert 'provider details' not in json.dumps(result)


def test_token_in_destination_is_rejected_before_any_send(monkeypatch):
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','1234:example_secret_token')
    monkeypatch.setattr(notifications.subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Do not send')))
    result=notifications.send_message('test')
    assert result['status']=='CONFIG_ERROR' and 'example_secret_token' not in json.dumps(result)


def test_notification_is_first_checkpoint_and_failure_does_not_block_flow(tmp_path,monkeypatch):
    from test_orchestrator import base_flow,write_flow,stub_registry
    from orchestrator_agent.runner import run_flow
    monkeypatch.setenv('DV_AGENT_START_NOTIFICATION','1')
    monkeypatch.setattr(notifications,'send_message',lambda text:dict(status='DELIVERY_FAILED',reason='Hermes unavailable'))
    events=[];calls=[]
    result=run_flow(write_flow(tmp_path,base_flow()),out_dir=tmp_path/'run',variables={},
                    registry=stub_registry(calls),event_sink=events.append)
    kinds=[e['event'] for e in events]
    assert kinds.index('notification_start')<kinds.index('notification_done')<kinds.index('tool_start')
    assert result['status']=='PASS' and len(calls)==2
    assert json.loads((tmp_path/'run/notification_plan.json').read_text())['status']=='DELIVERY_FAILED'


def test_code_notification_precedes_generation(tmp_path,monkeypatch):
    from orchestrator_agent.code_run import execute
    monkeypatch.setenv('DV_AGENT_START_NOTIFICATION','1')
    monkeypatch.setattr(notifications,'send_message',lambda text:dict(status='SENT',transport='hermes/telegram'))
    (tmp_path/'dv').mkdir();(tmp_path/'dv/testplan_doc.json').write_text('{}')
    def build(*a,**k):
        assert json.loads((tmp_path/'notification_code.json').read_text())['status']=='SENT'
        return dict(compile=dict(status='NOT_RUN'))
    execute(build,tmp_path,{},llm=object(),show=lambda text:None)


def test_disabled_and_dry_run_never_send(tmp_path,monkeypatch):
    monkeypatch.setattr(notifications,'send_message',lambda text:(_ for _ in ()).throw(AssertionError('No send expected')))
    assert notifications.notify_start(tmp_path,'plan')['status']=='SKIPPED'
    monkeypatch.setenv('DV_AGENT_START_NOTIFICATION','1')
    assert notifications.notify_start(tmp_path,'plan',dry_run=True)['status']=='SKIPPED'
    assert not list(tmp_path.iterdir())


def test_timeout_does_not_raise_or_leak_transport_body(monkeypatch):
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123')
    def process(*a,**k): raise subprocess.TimeoutExpired('hermes',15)
    monkeypatch.setattr(notifications.subprocess,'run',process)
    assert notifications.send_message('test')['status']=='DELIVERY_UNCERTAIN'


def test_fresh_can_recover_run_interrupted_after_only_startup_notification(tmp_path):
    from dv_agent.pipeline import clear_run
    (tmp_path/'notification_pipeline.json').write_text('{"status":"SENT"}')
    assert clear_run(tmp_path)==['notification_pipeline.json']


def test_readonly_hermes_launcher_falls_back_to_telegram(monkeypatch):
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123')
    monkeypatch.setattr(notifications.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stderr="hermes: [Errno 30] Read-only file system: '/root/.hermes/.install.lock'",stdout=''))
    calls=[]
    monkeypatch.setattr(notifications,'_telegram',lambda message,target:calls.append((message,target)) or dict(status='SENT',message_id=42,transport='telegram_api'))
    result=notifications.send_message('test')
    assert result['status']=='SENT' and result['message_id']==42 and calls==[('test','telegram:123')]


def test_cli_timeout_does_not_attempt_duplicate_fallback(monkeypatch):
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123')
    def timeout(*a,**k): raise subprocess.TimeoutExpired('hermes',15)
    monkeypatch.setattr(notifications.subprocess,'run',timeout)
    monkeypatch.setattr(notifications,'_telegram',lambda *a:(_ for _ in ()).throw(AssertionError('May already have sent')))
    assert notifications.send_message('test')['status']=='DELIVERY_UNCERTAIN'


def test_dns_failure_queues_message_and_flush_preserves_recipient_and_delivery(tmp_path,monkeypatch):
    monkeypatch.setenv('DV_AGENT_START_NOTIFICATION','1')
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123')
    monkeypatch.setattr(notifications,'send_message',lambda message:dict(status='DELIVERY_FAILED',retry_safe=True,reason='DNS unavailable'))
    result=notifications.notify_start(tmp_path/'run','plan')
    assert result['status']=='QUEUED'
    queue=json.loads(__import__('pathlib').Path(result['outbox']).read_text())
    assert 'token' not in queue and queue['target']=='telegram:123'
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:456')
    assert notifications.flush_outbox(tmp_path)[0]['status']=='CONFIG_ERROR'
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123')
    monkeypatch.setattr(notifications,'send_message',lambda message:dict(status='SENT',message_id=7))
    assert notifications.flush_outbox(tmp_path)[0]['status']=='SENT'
    assert notifications.flush_outbox(tmp_path)==[]


def test_direct_api_sanitizes_token_and_dns_error(monkeypatch):
    import socket
    import urllib.error
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123')
    monkeypatch.setenv('DV_AGENT_NOTIFICATION_TRANSPORT','telegram')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test_private_token')
    def failed(*a,**k): raise urllib.error.URLError(socket.gaierror(-3,'name resolution failed'))
    monkeypatch.setattr(notifications.urllib.request,'urlopen',failed)
    result=notifications.send_message('test')
    assert result['retry_safe'] and result['status']=='DELIVERY_FAILED'
    assert 'test_private_token' not in json.dumps(result)


def test_direct_api_requires_confirmation_message_id(monkeypatch):
    import io
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123')
    monkeypatch.setenv('DV_AGENT_NOTIFICATION_TRANSPORT','telegram')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test_private_token')
    monkeypatch.setattr(notifications.urllib.request,'urlopen',lambda *a,**k:io.BytesIO(b'{"ok":true,"result":{"message_id":99}}'))
    result=notifications.send_message('test')
    assert result==dict(status='SENT',transport='telegram_api',message_id=99)


def test_fresh_preserves_pending_outbox_and_can_be_repeated(tmp_path):
    from dv_agent.pipeline import clear_run
    queue=tmp_path/'notification_outbox';queue.mkdir();(queue/'queued.json').write_text('{"status":"PENDING"}')
    (tmp_path/'notification_pipeline.json').write_text('{"status":"QUEUED"}')
    assert clear_run(tmp_path)==['notification_pipeline.json']
    assert clear_run(tmp_path)==[] and (queue/'queued.json').exists()


# --- sending the generated testplan HTML ---------------------------------------------------------

def _document_env(monkeypatch, tmp_path, html='<html>plan</html>'):
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123')
    monkeypatch.setenv('DV_AGENT_SEND_TESTPLAN','1')
    monkeypatch.setenv('DV_AGENT_NOTIFICATION_TRANSPORT','auto')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test_private_token')
    plan=tmp_path/'run'/'dv';plan.mkdir(parents=True)
    (plan/'testplan_doc.html').write_text(html)
    return plan


def _fake_telegram(monkeypatch,sent,reply=None):
    class Reply:
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def read(self): return json.dumps(reply or {'ok':True,'result':{'message_id':77}}).encode()
    def urlopen(request,timeout):
        sent.append((request.full_url,request.get_header('Content-type'),request.data,timeout));return Reply()
    monkeypatch.setattr(notifications.urllib.request,'urlopen',urlopen)


def test_testplan_html_is_uploaded_as_a_document_with_a_confirmed_message_id(monkeypatch,tmp_path):
    plan=_document_env(monkeypatch,tmp_path);sent=[]
    _fake_telegram(monkeypatch,sent)
    result=notifications.notify_testplan(plan)
    assert result['status']=='SENT' and result['message_id']==77 and result['file']=='testplan_doc.html'
    url,content_type,body,timeout=sent[0]
    assert url=='https://api.telegram.org/bottest_private_token/sendDocument' and content_type.startswith('multipart/form-data; boundary=')
    assert b'name="chat_id"\r\n\r\n123' in body and b'filename="testplan_doc.html"' in body and b'<html>plan</html>' in body
    assert b'not signed off' in body and b'Run: run' in body
    saved=json.loads((plan/'notification_testplan.json').read_text())
    assert saved['status']=='SENT' and 'token' not in json.dumps(saved) and 'test_private_token' not in json.dumps(saved)


def test_same_testplan_is_not_sent_twice_but_a_changed_one_is(monkeypatch,tmp_path):
    plan=_document_env(monkeypatch,tmp_path);sent=[]
    _fake_telegram(monkeypatch,sent)
    assert notifications.notify_testplan(plan)['status']=='SENT'
    again=notifications.notify_testplan(plan)
    assert again['status']=='SKIPPED' and 'already delivered' in again['reason'] and len(sent)==1
    (plan/'testplan_doc.html').write_text('<html>revised</html>')
    assert notifications.notify_testplan(plan)['status']=='SENT' and len(sent)==2


def test_document_delivery_is_off_unconfigured_or_unsafe_by_default_rules(monkeypatch,tmp_path):
    plan=_document_env(monkeypatch,tmp_path)
    monkeypatch.setattr(notifications.urllib.request,'urlopen',lambda *a,**k:pytest.fail('must not send'))
    monkeypatch.setenv('DV_AGENT_SEND_TESTPLAN','0')
    assert notifications.notify_testplan(plan)['reason']=='testplan delivery disabled'
    monkeypatch.setenv('DV_AGENT_SEND_TESTPLAN','1');monkeypatch.delenv('DV_HITL_HERMES_TARGET')
    assert notifications.notify_testplan(plan)['reason']=='no Telegram target configured'
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','1234:example_secret_token')  # a token is never a destination
    assert notifications.send_document(plan/'testplan_doc.html')['status']=='CONFIG_ERROR'
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123');monkeypatch.setenv('DV_AGENT_NOTIFICATION_TRANSPORT','hermes')
    assert 'unverified' in notifications.send_document(plan/'testplan_doc.html')['reason']
    monkeypatch.setenv('DV_AGENT_NOTIFICATION_TRANSPORT','auto')
    assert notifications.send_document(plan/'missing.html')['status']=='DELIVERY_FAILED'
    (plan/'empty.html').write_text('')
    assert notifications.send_document(plan/'empty.html')['status']=='SKIPPED'
    (plan/'testplan_doc.html').unlink()
    assert notifications.notify_testplan(plan)['reason']=='no testplan HTML to send'


def test_failed_or_unconfirmed_upload_is_reported_and_only_a_failure_is_retried(monkeypatch,tmp_path):
    plan=_document_env(monkeypatch,tmp_path)
    monkeypatch.setattr(notifications.urllib.request,'urlopen',lambda *a,**k:(_ for _ in ()).throw(TimeoutError()))
    first=notifications.notify_testplan(plan)
    assert first['status']=='DELIVERY_UNCERTAIN'  # it may have arrived: not resent automatically
    assert notifications.notify_testplan(plan)['status']=='SKIPPED'
    import socket,urllib.error
    (plan/'notification_testplan.json').unlink()
    monkeypatch.setattr(notifications.urllib.request,'urlopen',lambda *a,**k:(_ for _ in ()).throw(urllib.error.URLError(socket.gaierror())))
    failed=notifications.notify_testplan(plan)
    assert failed['status']=='DELIVERY_FAILED' and failed['retry_safe'] is True
    sent=[];_fake_telegram(monkeypatch,sent)
    assert notifications.notify_testplan(plan)['status']=='SENT'  # a safe failure is retried on the next run


def test_plan_step_and_cli_send_the_html_only_after_a_passing_generation(monkeypatch,tmp_path):
    from dv_agent.cli import _notify_plan
    plan=_document_env(monkeypatch,tmp_path);sent=[]
    _fake_telegram(monkeypatch,sent)
    blocked={'status':'BLOCKED'}
    _notify_plan(plan,blocked)
    assert not sent and 'testplan_notification' not in blocked
    ok={'status':'PASS'}
    _notify_plan(plan,ok)
    assert ok['testplan_notification']=='SENT' and len(sent)==1


def test_orchestrator_sends_the_plan_when_the_testplan_step_passes(monkeypatch,tmp_path):
    from orchestrator_agent import runner
    from orchestrator_agent.tools import SPEC, ToolSpec
    plan=tmp_path/'run'/'dv';plan.mkdir(parents=True)
    (plan/'testplan_doc.json').write_text('{}');(plan/'testplan_doc.html').write_text('<html/>')
    calls=[]
    monkeypatch.setattr('dv_agent.core.notifications.notify_testplan',lambda directory,event=None:calls.append(Path(directory)) or {})
    monkeypatch.setattr(runner.guards,'post_testplan_check',lambda **k:[])
    flow={'version':1,'name':'t','steps':[{'id':'plan','tool':'dv_testplan','agent':'dv','args':{}}],'policy':{},
          'forbidden':[{'id':r,'title':t} for r,t in runner.guards.KNOWN_FORBIDDEN.items()]}
    flow_path=tmp_path/'flow.json';flow_path.write_text(json.dumps(flow))
    result=runner.run_flow(flow_path,out_dir=tmp_path/'run',variables={},registry={'dv_testplan':ToolSpec(
        'dv',SPEC,False,lambda args,ctx:dict(status='PASS',summary='ok',files=[str(plan/'testplan_doc.json')]))})
    assert result['status']=='PASS' and calls==[plan]


def _capture_upload(monkeypatch):
    from dv_agent.core import notifications
    calls=[]
    monkeypatch.setenv('DV_HITL_HERMES_TARGET','telegram:123')
    monkeypatch.delenv('DV_AGENT_SEND_WAVEFORM',raising=False)
    monkeypatch.setenv('DV_AGENT_NOTIFICATION_TRANSPORT','auto')
    def api(method,body,content_type,timeout):
        calls.append((method,body));return dict(status='SENT',message_id=7)
    monkeypatch.setattr(notifications,'_api_call',api)
    return notifications,calls


def test_a_waveform_is_uploaded_as_a_binary_file_and_the_outcome_is_recorded(tmp_path,monkeypatch):
    notifications,calls=_capture_upload(monkeypatch)
    fst=tmp_path/'quick_basic.fst';fst.write_bytes(b'\x00fst data')
    result=notifications.notify_waveform(fst,'quick_basic','PASS')
    assert result['status']=='SENT' and calls[0][0]=='sendDocument'
    assert b'filename="quick_basic.fst"' in calls[0][1] and b'application/octet-stream' in calls[0][1] and b'\x00fst data' in calls[0][1]
    assert b'quick_basic PASS' in calls[0][1]
    assert json.loads((tmp_path/'notification_waveform.json').read_text())['status']=='SENT'


def test_a_waveform_is_not_sent_when_disabled_unconfigured_missing_or_too_large(tmp_path,monkeypatch):
    notifications,calls=_capture_upload(monkeypatch)
    fst=tmp_path/'t.fst';fst.write_bytes(b'x')
    assert notifications.notify_waveform(tmp_path/'missing.fst')['status']=='SKIPPED'
    monkeypatch.setattr(notifications,'MAX_DOCUMENT_BYTES',0)
    assert notifications.notify_waveform(fst)['status']=='SKIPPED'
    monkeypatch.setenv('DV_AGENT_SEND_WAVEFORM','0')
    assert notifications.notify_waveform(fst)['reason']=='waveform delivery disabled'
    monkeypatch.delenv('DV_AGENT_SEND_WAVEFORM')
    monkeypatch.delenv('DV_HITL_HERMES_TARGET')
    assert notifications.notify_waveform(fst)['status']=='SKIPPED'
    assert not calls

