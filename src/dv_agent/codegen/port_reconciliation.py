"""Route source/RTL compatibility decisions through scoped, durable review."""
import json

from ..quality.human_review import (request_review,validate_receipt,current_plan_path,sha,write,PlanUpdated)
from .port_comparison import compare,width,width_options,condition_supported

UNIT='interface_port_alignment'
FIELDS=['mappings','width_choices','inactive_spec_ports']


def validate_proposal(request,bindings):
    contract=request['alignment_context']
    if not set(bindings)<=set(FIELDS): raise ValueError('Only port alignment decisions are allowed')
    if any(not isinstance(v,dict) for v in bindings.values()): raise ValueError('Port alignment fields must be maps')
    interfaces=contract['interfaces'];definition=contract['definition']
    if request['ports']!=definition['ports']: raise ValueError('Alignment port snapshot changed')
    decision=dict(spec_hash=sha(interfaces),rtl_hash=sha(definition),reviewer='Binding proposal',reason='Validation only',**bindings)
    result=compare(dict(interfaces=interfaces),definition,decision)
    if result['status']!='PASS':
        errors=result['errors']+[r['spec']+': '+', '.join(r.get('issues',[])) for r in result['rows'] if r['status']=='BLOCKED']
        raise ValueError('Proposed alignment does not independently validate: '+'; '.join(errors)[:1600])


def decision_from_receipt(plan,definition,request,receipt):
    validate_receipt(request,receipt)
    contract=request['alignment_context']
    if sha(contract['interfaces'])!=sha(plan.get('interfaces')) or sha(contract['definition'])!=sha(definition):
        raise ValueError('Approved alignment belongs to a different spec/RTL snapshot')
    test=receipt['status']=='TEST_AUTO_APPROVED'
    if test and not plan.get('test_only'): raise ValueError('Test-only alignment cannot revise a normal plan')
    return dict(spec_hash=sha(plan['interfaces']),rtl_hash=sha(definition),reviewer=receipt['actor'],reason=receipt['reason'],
                **receipt['bindings'],review_status=receipt['status'],test_only=test,
                request_id=request['id'],source_id=('QUICK-TEST-' if test else 'HUMAN-')+request['id'],
                assumptions=receipt.get('assumptions',[]))


def recover_decisions(plan,definition,out):
    """Recover a published plan approval after interruption before mapping publication."""
    for record in reversed(plan.get('human_approvals',[])+plan.get('quick_test_approvals',[])):
        if record.get('unit')!=UNIT: continue
        path=out/'human_review'/record['request_id']/'request.json'
        if not path.is_file(): continue
        request=json.loads(path.read_text());contract=request.get('alignment_context',{})
        if sha(contract.get('interfaces'))!=sha(plan.get('interfaces')) or sha(contract.get('definition'))!=sha(definition): continue
        return decision_from_receipt(plan,definition,request,record)
    return None


def reconcile(plan,definition,out,report):
    """Review only remediable ambiguity. Never approve a real mismatch or audit defect. Returns why when it cannot ask."""
    previous=report.get('review_decisions') or {}
    if previous and (previous.get('spec_hash')!=sha(plan.get('interfaces')) or previous.get('rtl_hash')!=sha(definition)):
        report=compare(plan,definition)
        if report['status']=='PASS':
            write(out/'port_mapping_history'/(sha(previous)+'.json'),previous)
            write(out/'interface_port_mapping.json',{})
            raise PlanUpdated('Archived stale port mapping; validate current direct-source alignment')
    blocked=[r for r in report['rows'] if r['status']=='BLOCKED']
    if not blocked: return
    signals=plan['interfaces'].get('signals') or [s for g in plan['interfaces'].get('groups',[]) for s in g.get('signals',[])]
    by_name={s['name']:s for s in signals}
    ports={p['name']:p for p in definition['ports']}
    suggestions={k:{} for k in FIELDS};candidates={};questions=[];excerpts=[]
    for row in blocked:
        s=by_name[row['spec']];name=s['name'];choices=width_options(s.get('width'));bits=width(s.get('width'))
        if s.get('direction') not in ('input','output','inout') or s.get('direction_documented') is False or s.get('width_documented') is False:
            return f'{name}: its direction or width is not documented in its quote'
        if any(issue not in ('Missing/ambiguous RTL match; provide a reviewed alias mapping',
                             'Width or configuration-dependent width is unresolved') for issue in row.get('issues',[])):
            return f"{name}: {'; '.join(row.get('issues',[]))}"
        if bits is None and not choices: return f"{name}: its width {s.get('width')!r} cannot be read"
        eligible=[p for p in definition['ports'] if p['name'] in report['unmatched_rtl']
                  and p['direction']==s['direction'] and width(p.get('width',p.get('range'))) in (choices or {bits})]
        if row.get('rtl'):
            p=ports[row['rtl']]
        elif eligible:
            candidates[name]=[p['name'] for p in eligible]
            p=eligible[0] if len(eligible)==1 else None
            if p: suggestions['mappings'][name]=p['name']
        elif condition_supported(s):
            suggestions['inactive_spec_ports'][name]='Documented conditional output is disabled in the selected RTL configuration.'
            p=None
        else:
            return (f"{name}: no RTL port matches, and its condition {s.get('availability','')!r} is not confirmed by its source" if s.get('availability')
                    else f'{name}: no RTL port matches, and the specification states no condition for it')
        if p and choices:
            actual=width(p.get('width',p.get('range')))
            if actual not in choices: return f'{name}: RTL width {actual} is not one of the documented widths {sorted(choices)}'
            suggestions['width_choices'][name]=actual
        questions.append(f"{name}: spec width {s.get('width')}, direction {s['direction']}; "+
                         (f"RTL {row['rtl']} width {row.get('rtl_width')}" if row.get('rtl') else
                          'RTL candidates '+', '.join(candidates.get(name,[])) if eligible else
                          'optional under '+s.get('availability','')+'; absent from RTL'))
        if s.get('quote') and s.get('chunk_id'):
            excerpts.append(dict(source_id=s['chunk_id'],start=None,end=None,text=s['quote'],
                                 doc_path=s.get('doc_path',''),pages=s.get('pages',[])))
    contract=dict(interfaces=plan['interfaces'],definition=definition,candidates=candidates,proposed_bindings=suggestions)
    evidence=dict(source_excerpts=excerpts,documented_items=[])
    request,receipt=request_review(out,plan,definition,UNIT,questions,evidence,context=dict(
        alignment_context=contract,understanding='The specification describes the logical interface and permitted variants. '
        'The configured RTL inventory defines physical port names and selected widths. Confirm aliases and the selected '
        'variant together before any interface or driver is built. Optional-port absence needs an explicit configuration decision.'))
    from ..plan.approved_clarifications import apply_approval
    apply_approval(current_plan_path(out),request,receipt)
    updated=json.loads(current_plan_path(out).read_text())
    decision=decision_from_receipt(updated,definition,request,receipt)
    previous_path=out/'interface_port_mapping.json'
    if previous_path.is_file():
        previous=json.loads(previous_path.read_text())
        if previous!=decision: write(out/'port_mapping_history'/(sha(previous)+'.json'),previous)
    write(out/'interface_port_mapping.json',decision)
    raise PlanUpdated('Port alignment reviewed; reload the revised plan and independently validate again')
