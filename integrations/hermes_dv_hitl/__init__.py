"""Hermes gateway plugin; receives human Telegram commands, never agent approvals."""
import json
import os
import re
from pathlib import Path


def approve_command(raw_args, *, platform='', source=None, **kwargs):
    allowed={x.strip() for x in os.getenv('DV_HITL_TELEGRAM_USER_IDS','').split(',') if x.strip()}
    target=os.getenv('DV_HITL_HERMES_TARGET','')
    if (platform!='telegram' or source is None or str(getattr(source,'user_id','')) not in allowed
            or target!='telegram:'+str(getattr(source,'chat_id',''))):
        return 'Approval refused: an authorized human Telegram user in the configured chat is required.'
    try:
        first,_,rest=raw_args.strip().partition(' ')
        rid=first if re.fullmatch(r'[a-f0-9]{20}',first) else None
        reply=rest if rid else raw_args.strip()
        configured=os.getenv('DV_HITL_RUNS_ROOT')
        if not configured: raise ValueError('Set DV_HITL_RUNS_ROOT on the gateway')
        root=Path(configured).resolve()
        matches=[p for p in root.glob('*/human_review/'+(rid or '*')) if p.resolve().is_relative_to(root)
                 and (p/'request.json').is_file() and (rid or not (p/'approval.json').exists())]
        # Natural replies must resolve to one current request, never an arbitrary run.
        if not rid:
            from dv_agent.quality.human_review import sha
            matches=[p for p in matches if (p.parents[1]/'dv/testplan_doc.json').is_file() and
                     sha(json.loads((p.parents[1]/'dv/testplan_doc.json').read_text())) ==
                     json.loads((p/'request.json').read_text())['plan_hash']]
        if len(matches)!=1:
            choices=', '.join(p.name for p in matches[:4])
            raise ValueError('Please identify which pending decision you mean'+(': '+choices if choices else '. No current request found.'))
        folder=matches[0]
        request=json.loads((folder/'request.json').read_text())
        # Reject approval of an old request after a fresh plan supersedes it.
        from dv_agent.quality.human_review import sha
        run=folder.parents[1]
        current=json.loads((run/'dv/testplan_doc.json').read_text())
        if sha(current)!=request['plan_hash'] and not any(a['request_id']==rid for a in current.get('human_approvals',[])):
            raise ValueError('Testplan changed; ask the orchestrator for a fresh request')
        definition=json.loads((run/'rtl/interface_definition.json').read_text())
        ports={p['name']:p for p in definition['ports']}
        if any(ports.get(p['name'])!=p for p in request['ports']):
            raise ValueError('Interface changed; request a fresh clarification')
        rid=request['id']
        reference='telegram:'+str(source.chat_id)+':'+str(kwargs.get('session_id','gateway'))
        from dv_agent.quality.human_dialogue import respond
        from dv_agent.core.llm import MetaClient
        llm=MetaClient() if os.getenv('MODEL_API_KEY','').strip() else None
        result=respond(folder,request,reply,actor=str(source.user_id),channel='telegram',reference=reference,llm=llm)
        if not (folder/'approval.json').exists():
            return result+'\nReply: /dvapprove '+rid+' followed by your confirmation or correction.'
        receipt=json.loads((folder/'approval.json').read_text())
        from dv_agent.plan.approved_clarifications import apply_approval
        apply_approval(run/'dv/testplan_doc.json',request,receipt)
        return f"Human approval recorded for {rid} at {receipt['approved_at']}. The testplan JSON/Markdown/HTML have been revised with the approval. Resume /code if it is not waiting."
    except (ValueError,KeyError,OSError,TypeError) as exc:
        return 'Approval not recorded: '+(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)


def register(ctx):
    ctx.register_command('dvapprove',handler=approve_command,
        description='Approve a pending Silicon Copilot infrastructure clarification',
        args_hint='[request-id] your answer or confirmation in ordinary English')
