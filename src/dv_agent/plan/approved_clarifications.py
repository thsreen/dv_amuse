"""Dedicated, versioned testplan revision from explicit human infrastructure approval."""
import json
from pathlib import Path

from ..core.fsutil import atomic_write_text
from ..quality.human_review import sha, validate_receipt, utc


def apply_approval(plan_path, request, receipt):
    import fcntl
    path=Path(plan_path)
    with (path.parent/'.human_revision.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        return _apply_approval(path,request,receipt)


def _apply_approval(plan_path, request, receipt):
    validate_receipt(request,receipt)
    path=Path(plan_path);doc=json.loads(path.read_text())
    test=receipt.get('status')=='TEST_AUTO_APPROVED'
    if test and (not doc.get('test_only') or not (path.parent.parent/'quick_testing.json').is_file()):
        raise ValueError('Test auto approvals may only revise isolated quick-testing plans')
    collection='quick_test_approvals' if test else 'human_approvals'
    existing=next((a for a in doc.get(collection,[]) if a['request_id']==request['id']),None)
    if existing:
        if existing['bindings']!=receipt['bindings']: raise ValueError('Conflicting previously applied approval')
        return
    if sha(doc)!=request['plan_hash']: raise ValueError('Testplan changed; request a new human clarification')
    original=path.read_text();before=sha(doc)
    source_id=('QUICK-TEST-' if test else 'HUMAN-')+request['id']
    statement=('QUICK TESTING ONLY inferred binding for ' if test else 'Human-approved infrastructure binding for ')+request['unit']+': '+json.dumps(receipt['bindings'],sort_keys=True)
    comment=(f"Automatically approved for quick testing on {receipt['approved_at']}; NOT human approval or sign-off. Reason: {receipt['reason']}. Assumptions: "+'; '.join(receipt.get('assumptions',[])) if test else
             f"Approved by user {receipt['actor']} on {receipt['approved_at']} via {receipt['channel']}; acknowledgement {receipt['reference']}. Reason: {receipt['reason']}")
    section_id='quick_test_clarifications' if test else 'human_clarifications'
    section=next((s for s in doc['sections'] if s['id']==section_id),None)
    if section is None:
        section=dict(id=section_id,heading='Quick-testing inferred auto approvals' if test else 'Human-approved infrastructure clarifications',generator='entries',status='PASS',entries=[])
        doc['sections'].append(section)
    entry=dict(id=source_id,kind='human_clarification',text=statement+' — '+comment,details=[],validation=[],
               comments=comment,provenance='INFERRED' if test else 'DOCUMENTED',
               inference_reason=receipt['reason'] if test else '',
               source_kind='QUICK_TEST_AUTO_APPROVAL' if test else 'HUMAN_APPROVED_CLARIFICATION',
               cited_chunk_ids=[source_id],cited_req_ids=[],approval_request_id=request['id'])
    section['entries'].append(entry);section.pop('subsections',None)
    doc.setdefault(collection,[]).append(dict(receipt,unit=request['unit'],scope='infrastructure_only',source_id=source_id))
    doc.setdefault('evidence_index',{})[source_id]=dict(excerpt=statement+' — '+comment,path='human_review/'+request['id'],
        location=('Test auto approval ' if test else 'Human approval ')+receipt['reference'],summary=statement,
        source_kind='QUICK_TEST_AUTO_APPROVAL' if test else 'HUMAN_APPROVED_CLARIFICATION')
    from .clock_review import reflect_clock_review
    reflect_clock_review(doc,request,receipt,source_id,comment)
    # Preserve specification facts and existing verification objectives. The new section
    # is a scoped approved addendum, never a silent rewrite of the original source.
    from .testplan_doc import render_markdown
    from ..report.html_report import render_html
    markdown=render_markdown(doc);html=render_html(markdown)
    version=path.parent/'human_revisions'/request['id'];version.mkdir(parents=True,exist_ok=True)
    files={'testplan_doc.json':json.dumps(doc,indent=2)+'\n','testplan_doc.md':markdown,'testplan_doc.html':html}
    atomic_write_text(version/'before.json',original)
    for name,text in files.items(): atomic_write_text(version/name,text)
    atomic_write_text(version/'revision.json',json.dumps(dict(request_id=request['id'],actor=receipt['actor'],
        before_hash=before,after_hash=sha(doc),at=utc(),status='READY_TO_PUBLISH'),indent=2)+'\n')
    # JSON is the final commit marker. No model or code generation occurs in this workflow.
    atomic_write_text(path.with_suffix('.md'),markdown)
    atomic_write_text(path.with_suffix('.html'),html)
    atomic_write_text(path,files['testplan_doc.json'])
    atomic_write_text(version/'revision.json',json.dumps(dict(request_id=request['id'],actor=receipt['actor'],
        before_hash=before,after_hash=sha(doc),at=utc(),status='APPLIED'),indent=2)+'\n')
