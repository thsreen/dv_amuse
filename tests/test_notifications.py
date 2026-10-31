"""Notification transport is always mocked; no real bot is contacted by tests."""
import json
import subprocess
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
