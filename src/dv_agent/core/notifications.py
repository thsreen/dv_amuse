"""Hermes notifications with a bootstrap-safe Telegram fallback and durable outbox."""
import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .fsutil import atomic_write_text


def _target():
    return os.getenv('DV_HITL_HERMES_TARGET','').strip()


def _token():
    if os.getenv('TELEGRAM_BOT_TOKEN'): return os.environ['TELEGRAM_BOT_TOKEN'].strip()
    path=Path(os.getenv('DV_HITL_HERMES_ENV_FILE',str(Path(os.getenv('HERMES_HOME',str(Path.home()/'.hermes')))/'.env')))
    try:
        for line in path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1)
                if key.strip()=='TELEGRAM_BOT_TOKEN': return value.strip().strip('\"\'')
    except OSError: pass
    return ''


def _telegram(message,target):
    body=urllib.parse.urlencode(dict(chat_id=target.split(':',1)[1],text=message)).encode()
    return _api_call('sendMessage',body,'application/x-www-form-urlencoded',15)


def _api_call(method,body,content_type,timeout):
    token=_token()
    if not token: return dict(status='UNCONFIGURED',reason='Telegram token unavailable in Hermes configuration')
    request=urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,data=body,method='POST',
                                   headers={'Content-Type':content_type})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response: result=json.load(response)
        if result.get('ok') and isinstance(result.get('result',{}).get('message_id'),int):
            return dict(status='SENT',transport='telegram_api',message_id=result['result']['message_id'])
        return dict(status='DELIVERY_FAILED',reason='Telegram did not confirm acceptance')
    except urllib.error.HTTPError as exc:
        return dict(status='DELIVERY_FAILED',reason='Telegram HTTP error',http_status=exc.code)
    except urllib.error.URLError as exc:
        # No request reached Telegram if DNS failed or a connection could not be made.
        safe=isinstance(exc.reason,(socket.gaierror,ConnectionRefusedError))
        return dict(status='DELIVERY_FAILED' if safe else 'DELIVERY_UNCERTAIN',
                    reason='Telegram DNS resolution failed' if isinstance(exc.reason,socket.gaierror) else 'Telegram connection failed',
                    retry_safe=safe)
    except (TimeoutError,ValueError,OSError):
        return dict(status='DELIVERY_UNCERTAIN',reason='Telegram response unavailable; inspect bot chat before resending')


def send_message(message):
    target=_target()
    if not target: return dict(status='UNCONFIGURED',reason='DV_HITL_HERMES_TARGET is not set')
    if not re.fullmatch(r'telegram:-?\d+',target):
        return dict(status='CONFIG_ERROR',reason='Destination must be telegram:<numeric chat ID>, never a bot token')
    mode=os.getenv('DV_AGENT_NOTIFICATION_TRANSPORT','auto').lower()
    if mode not in ('auto','hermes','telegram'):
        return dict(status='CONFIG_ERROR',reason='Notification transport must be auto, hermes or telegram')
    if mode=='telegram': return _telegram(message,target)
    try:
        result=subprocess.run([os.getenv('DV_HITL_HERMES_BIN','hermes'),'send','--json','--to',target],
                              input=message,capture_output=True,text=True,timeout=15)
        if result.returncode==0:
            try: receipt=json.loads(result.stdout)
            except (ValueError,TypeError): receipt={}
            if not isinstance(receipt,dict): receipt={}
            if receipt.get('skipped'):
                return dict(status='DELIVERY_SKIPPED',transport='hermes/telegram',
                            reason='Hermes skipped delivery; no Telegram message was sent')
            mid=receipt.get('message_id')
            confirmed=(receipt.get('success') is True and not receipt.get('error')
                       and isinstance(mid,(str,int)) and not isinstance(mid,bool) and str(mid).isdigit())
            if confirmed:
                if receipt.get('platform') not in (None,'telegram') or (
                        receipt.get('chat_id') is not None and str(receipt['chat_id'])!=target.split(':',1)[1]):
                    return dict(status='DELIVERY_UNCERTAIN',transport='hermes/telegram',
                                reason='Hermes receipt destination does not match the configured Telegram chat')
                return dict(status='SENT',transport='hermes/telegram',message_id=str(mid))
            # Unknown acknowledgement may represent a send: never blindly resend.
            return dict(status='DELIVERY_UNCERTAIN',transport='hermes/telegram',
                        reason='Hermes exited successfully without a confirmed Telegram message ID')
        # Fall back only when Hermes failed BEFORE delivery. Generic CLI failures
        # and timeouts may represent successful sends with a lost acknowledgement.
        bootstrap=bool(re.search(r'(?:Read-only file system|Permission denied).*install\.lock',result.stderr))
        if mode=='auto' and bootstrap:
            return dict(_telegram(message,target),fallback='Hermes installation lock is not writable')
        return dict(status='DELIVERY_FAILED',reason='Hermes CLI returned a failure',exit_code=result.returncode)
    except FileNotFoundError:
        if mode=='auto': return dict(_telegram(message,target),fallback='Hermes executable unavailable')
        return dict(status='DELIVERY_FAILED',reason='Hermes executable unavailable')
    except subprocess.TimeoutExpired:
        return dict(status='DELIVERY_UNCERTAIN',reason='Hermes timed out; inspect bot chat before resending')
    except OSError as exc:
        return dict(status='DELIVERY_FAILED',reason=type(exc).__name__)


MAX_DOCUMENT_BYTES=50*1024*1024  # Telegram's limit for a bot upload
MAX_CAPTION=1024


def _multipart(fields,filename,content,mime):
    boundary='----dvagent'+hashlib.sha256(content[:4096]+filename.encode()).hexdigest()[:24]
    parts=[]
    for key,value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    safe=re.sub(r'[^A-Za-z0-9._-]','_',filename)
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{safe}"\r\n'
                 f'Content-Type: {mime}\r\n\r\n'.encode()+content+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts),f'multipart/form-data; boundary={boundary}'


def send_document(path,caption='',mime='text/html'):
    """Send one file to the configured Telegram chat. Uses the Bot API with the token Hermes already holds.

    The Hermes CLI has no verified file option, so transport 'hermes' is refused rather than guessed.
    A timeout or an unconfirmed reply is DELIVERY_UNCERTAIN and is never retried automatically.
    """
    target=_target()
    if not target: return dict(status='UNCONFIGURED',reason='DV_HITL_HERMES_TARGET is not set')
    if not re.fullmatch(r'telegram:-?\d+',target):
        return dict(status='CONFIG_ERROR',reason='Destination must be telegram:<numeric chat ID>, never a bot token')
    mode=os.getenv('DV_AGENT_NOTIFICATION_TRANSPORT','auto').lower()
    if mode=='hermes':
        return dict(status='CONFIG_ERROR',reason='Document delivery needs transport auto or telegram (Hermes file sending is unverified)')
    path=Path(path)
    try: content=path.read_bytes()
    except OSError: return dict(status='DELIVERY_FAILED',reason='Document is not readable')
    if not content or len(content)>MAX_DOCUMENT_BYTES:
        return dict(status='SKIPPED',reason='Document is empty or larger than Telegram allows')
    body,content_type=_multipart(dict(chat_id=target.split(':',1)[1],caption=caption[:MAX_CAPTION]),path.name,content,mime)
    return dict(_api_call('sendDocument',body,content_type,60),transport='telegram_api',file=path.name,bytes=len(content))


def notify_testplan(plan_dir,event=None):
    """Send testplan_doc.html once it has been generated; never twice for the same content.

    The plan can hold specification excerpts, so it goes only to the configured chat, and
    DV_AGENT_SEND_TESTPLAN=0 turns this off. A failure never affects the run.
    """
    plan_dir=Path(plan_dir);html=plan_dir/'testplan_doc.html'
    if os.getenv('DV_AGENT_SEND_TESTPLAN','1').lower() in ('0','off','false'):
        return dict(status='SKIPPED',reason='testplan delivery disabled')
    if not _target(): return dict(status='SKIPPED',reason='no Telegram target configured')
    if not html.is_file(): return dict(status='SKIPPED',reason='no testplan HTML to send')
    digest=hashlib.sha256(html.read_bytes()).hexdigest()
    report=plan_dir/'notification_testplan.json'
    try: previous=json.loads(report.read_text())
    except (OSError,ValueError): previous={}
    if isinstance(previous,dict) and previous.get('sha256')==digest and previous.get('status') in ('SENT','DELIVERY_UNCERTAIN'):
        return dict(status='SKIPPED',reason='this testplan was already delivered',sha256=digest)
    stamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
    run=plan_dir.parent.name if plan_dir.name=='dv' else plan_dir.name
    caption=(f'Silicon Copilot: test plan generated. Run: {run}. {stamp}. '
             'Generated, not signed off: every item needs engineer review.')
    if event: event('testplan_notification',status='SENDING',file=html.name)
    result=dict(send_document(html,caption),at=stamp,sha256=digest)
    _save(report,result)
    if event: event('testplan_notification',status=result['status'],reason=result.get('reason',''),file=html.name)
    return result


def notify_waveform(path,test_name='',status=''):
    """Send a waveform to the configured chat, and record the outcome beside it. A failure never affects the run.

    A waveform holds the design's signal values, so it goes only to the configured chat, and DV_AGENT_SEND_WAVEFORM=0 turns this off.
    """
    path=Path(path)
    if os.getenv('DV_AGENT_SEND_WAVEFORM','1').lower() in ('0','off','false'):
        return dict(status='SKIPPED',reason='waveform delivery disabled')
    if not _target(): return dict(status='SKIPPED',reason='no Telegram target configured')
    if not path.is_file(): return dict(status='SKIPPED',reason='no waveform file to send')
    label=' '.join(part for part in (test_name or path.stem,status) if part)
    result=dict(send_document(path,f'Silicon Copilot waveform: {label}. Open with GTKWave or Surfer.','application/octet-stream'),
                at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    _save(path.with_name('notification_waveform.json'),result)
    return result


def _save(path,record):
    atomic_write_text(path,json.dumps(record,indent=2)+'\n')


def notify_start(out,operation,event=None,*,dry_run=False):
    if dry_run: return dict(status='SKIPPED',reason='dry run')
    if os.getenv('DV_AGENT_START_NOTIFICATION','1').lower() in ('0','off','false'):
        return dict(status='SKIPPED',reason='startup notifications disabled')
    out=Path(out);stamp=datetime.now(timezone.utc).isoformat()
    if event: event('notification_start',id='startup_notification',operation=operation)
    message=f'Silicon Copilot: {operation} started. Run: {out.name}. Started: {stamp}. This is a startup notification; no approval is requested.'
    result=dict(send_message(message),operation=operation,at=stamp,message=message)
    if result.get('retry_safe'):
        identity=hashlib.sha256((str(out.resolve())+message).encode()).hexdigest()[:24]
        queue=out/'notification_outbox'/f'{identity}.json'
        _save(queue,dict(status='PENDING',message=message,target=_target(),created_at=stamp,id=identity))
        result.update(status='QUEUED',outbox=str(queue))
    _save(out/f'notification_{operation}.json',result)
    if event: event('notification_done',id='startup_notification',status=result['status'],reason=result.get('reason',''),operation=operation)
    return result


def flush_outbox(root):
    results=[]
    for path in sorted(Path(root).glob('*/notification_outbox/*.json')):
        # Never send a queued message to a newly configured recipient implicitly.
        import fcntl
        with path.with_suffix('.lock').open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            record=json.loads(path.read_text())
            if record['status']!='PENDING': continue
            if record['target']!=_target():
                results.append(dict(id=record['id'],status='CONFIG_ERROR',reason='Queued recipient differs from configuration'));continue
            record['status']='IN_FLIGHT'
            _save(path,record)
            delivery=send_message(record['message'])
            record['attempts']=record.get('attempts',0)+1
            record['delivery']=delivery
            if delivery['status']=='SENT': record['status']='SENT'
            elif delivery['status']=='DELIVERY_UNCERTAIN': record['status']='DELIVERY_UNCERTAIN'
            else: record['status']='PENDING'
            _save(path,record)
            if delivery['status']=='SENT':
                for report in path.parents[1].glob('notification_*.json'):
                    current=json.loads(report.read_text())
                    if Path(current.get('outbox','')).name!=path.name: continue
                    current.pop('reason',None)
                    current.update(delivery)
                    _save(report,current)
            results.append(dict(id=record['id'],**delivery))
    return results


def main():
    parser=argparse.ArgumentParser(description='Send pending Silicon Copilot notifications from a network-enabled host')
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--flush',type=Path,help='runs directory containing notification outboxes')
    action.add_argument('--test',action='store_true',help='send one delivery-check message and print the provider receipt')
    action.add_argument('--send-testplan',type=Path,help='send testplan_doc.html from this plan directory (the dv folder of a run)')
    action.add_argument('--send-waveform',type=Path,help='send this waveform file')
    args=parser.parse_args()
    # Use project configuration without copying Hermes credentials into this file.
    from orchestrator_agent.cli import load_env_file
    load_env_file(Path(__file__).resolve().parents[3]/'.env')
    if args.send_waveform:
        result=notify_waveform(args.send_waveform)
    elif args.send_testplan:
        # Explicit resend: forget the recorded delivery so identical content is sent again on request.
        (args.send_testplan/'notification_testplan.json').unlink(missing_ok=True)
        result=notify_testplan(args.send_testplan)
    else:
        result=send_message('Silicon Copilot: Telegram delivery check. No approval is requested.') if args.test else flush_outbox(args.flush)
    print(json.dumps(result,indent=2))
    if (args.test or args.send_testplan or args.send_waveform) and result['status'] not in ('SENT',): raise SystemExit(1)


if __name__=='__main__': main()
