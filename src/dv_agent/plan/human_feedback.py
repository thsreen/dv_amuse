"""Editable Markdown feedback and evidence-aware report review, separate from execution."""
import json
import re
from pathlib import Path
from ..core.fsutil import atomic_write_text

START='<!-- dv-human-feedback -->'
END='<!-- /dv-human-feedback -->'


def render(doc):
    from ..quality.human_review import sha
    existing={r['section']:r for r in doc.get('human_feedback',{}).get('items',[])}
    lines=['','## Human feedback and completion review','',
           '_Edit Requested to DONE or OPEN and add feedback and evidence (source IDs or run-relative file paths). '
           'Apply using review-feedback. DONE means human review completed, not simulation PASS or design sign-off._','',
           '<!-- dv-review-snapshot:'+sha({k:v for k,v in doc.items() if k!='human_feedback'})+' -->',
           START,'| Section | Requested | Feedback | Evidence | Assessment |','|---|---|---|---|---|']
    if doc.get('human_feedback'):
        result=doc['human_feedback']
        lines[3:3]=[f"**Review result: {result['status']}** — {result['reviewer']} ({result['at']}). Report review only.",'']
    for section in doc.get('sections',[]):
        if not section.get('id'): continue
        row=existing.get(section['id'],{})
        assessment=row.get('status','OPEN')+(': '+'; '.join(row['reasons']) if row.get('reasons') else '')
        cells=[section['id'],row.get('requested','OPEN'),row.get('feedback',''),row.get('evidence',''),assessment]
        lines.append('| '+' | '.join(str(c).replace('|','/').replace('\n',' ') for c in cells)+' |')
    return '\n'.join(lines+[END,''])


def apply(out, file, reviewer):
    from ..codegen.build import project_lock
    from ..quality.human_review import utc
    from .testplan_doc import render_markdown
    from ..report.html_report import render_html
    if not reviewer.strip(): raise ValueError('Name the human reviewer')
    out=Path(out).resolve();path=out/'testplan_doc.json'
    text=Path(file).read_text()
    if text.count(START)!=1 or text.count(END)!=1: raise ValueError('Feedback Markdown needs one marked review table')
    with project_lock(out.parent if out.name=='dv' else out):
        original=path.read_text();doc=json.loads(original)
        from ..quality.human_review import sha
        snapshot=re.search(r'<!-- dv-review-snapshot:([a-f0-9]{64}) -->',text)
        if not snapshot or snapshot[1]!=sha({k:v for k,v in doc.items() if k!='human_feedback'}):
            raise ValueError('Report changed or feedback lacks a snapshot; render the latest report and review it again')
        sections={s['id']:s for s in doc['sections']};items=[];seen=set()
        for line in text.split(START)[1].split(END)[0].splitlines():
            if not line.strip().startswith('|'): continue
            cells=[c.strip() for c in line.strip().strip('|').split('|')]
            if cells[0]=='Section' or cells[0].startswith('---'): continue
            if len(cells)!=5 or cells[0] not in sections or cells[0] in seen:
                raise ValueError('Feedback rows must uniquely identify existing sections and have five columns')
            sid,requested,comment,evidence,_=cells;seen.add(sid)
            if requested not in ('OPEN','DONE'): raise ValueError('Requested status must be OPEN or DONE')
            refs=[r.strip() for r in evidence.split(',') if r.strip()]
            valid=bool(refs)
            for ref in refs:
                if ref in doc.get('evidence_index',{}): continue
                target=(out/ref).resolve()
                if not target.is_relative_to(out) or not target.is_file() or target.stat().st_size==0: valid=False
            ready=sections[sid]['status']=='PASS'
            done=requested=='DONE' and bool(comment) and valid and ready
            reasons=[]
            if requested=='DONE':
                if not comment: reasons.append('Reviewer feedback is missing')
                if not valid: reasons.append('Evidence is missing or unresolved')
                if not ready: reasons.append('Section generation is not PASS; feedback cannot clear its blocker')
            items.append(dict(section=sid,requested=requested,feedback=comment,evidence=evidence,
                              status='DONE' if done else 'NEEDS_WORK' if requested=='DONE' else 'OPEN',reasons=reasons))
        if seen!=set(sections): raise ValueError('Keep a feedback row for every report section')
        report=dict(status='DONE' if items and all(r['status']=='DONE' for r in items) else 'NEEDS_WORK',
                    scope='human report review only; execution and sign-off unchanged',reviewer=reviewer,at=utc(),items=items)
        doc['human_feedback']=report
        version=out/'feedback_revisions'/report['at'].replace(':','').replace('.','')
        version.mkdir(parents=True)
        atomic_write_text(version/'before.json',original)
        atomic_write_text(version/'submitted.md',text)
        atomic_write_text(version/'analysis.json',json.dumps(report,indent=2)+'\n')
        markdown=render_markdown(doc)
        heading='## Human feedback and completion review'
        if heading in text and text.split(heading)[0].strip():
            # Retain human edits elsewhere in the full report; replace only this review block.
            before,rest=text.split(heading,1)
            _,after=rest.split(END,1)
            markdown=before+render(doc).lstrip()+'\n'+after
        atomic_write_text(out/'testplan_doc.md',markdown)
        atomic_write_text(out/'testplan_doc.html',render_html(markdown))
        atomic_write_text(path,json.dumps(doc,indent=2)+'\n')
        return report
