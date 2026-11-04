"""Compare independent specification/RTL port inventories before consuming physical ports."""
import json
import re
from pathlib import Path
from ..core.fsutil import atomic_write_text
from ..quality.human_review import sha
from ..ingest.extract import condition_stated
from ..core.progress import emit


def width(value):
    if type(value) is int: return value if value>0 else None
    value=str(value or '').strip()
    if re.fullmatch(r'\d+(?:\s*bits?)?',value,re.I): return int(value.split()[0]) or None
    match=re.fullmatch(r'\[?(\d+)\s*:\s*(\d+)\]?',value)
    return abs(int(match[1])-int(match[2]))+1 if match else None


def width_options(value):
    """Explicit finite choices only; never expand a symbolic expression or range."""
    if isinstance(value,list):
        return set(value) if len(value)>1 and all(type(n) is int and n>0 for n in value) else set()
    tokens=re.split(r'\s*(?:,\s*(?:or\s+)?|/|\bor\b)\s*',str(value).strip(),flags=re.I)
    if len(tokens)<2 or not all(re.fullmatch(r'[0-9]+',t) and int(t)>0 for t in tokens): return set()
    return {int(t) for t in tokens}


def condition_supported(signal):
    if not signal.get('availability'): return False
    if signal.get('documented',{}).get('availability') is not False: return True
    condition=re.sub(r'\s+',' ',signal['availability']).strip().casefold()
    quote=re.sub(r'\s+',' ',signal.get('quote','')).strip().casefold()
    start=quote.find(condition)
    return start>=0 and not re.search(r'\b(?:not|never)\s+$',quote[:start])


def compare(plan, definition, decisions=None, *, validate=True):
    spec=plan.get('interfaces') or {}
    hashes=dict(spec_hash=sha(spec),rtl_hash=sha(definition))
    errors=[]
    decisions=decisions or {}
    if not isinstance(decisions,dict):
        errors.append('Mapping decisions must be a JSON object')
        decisions={}
    if decisions and (any(decisions.get(k)!=v for k,v in hashes.items()) or not decisions.get('reviewer') or not decisions.get('reason')):
        errors.append('Mapping decision is stale or lacks reviewer/reason')
    for key,typ in [('mappings',str),('width_choices',int),('inactive_spec_ports',str)]:
        value=decisions.get(key,{})
        if not isinstance(value,dict) or any(type(v) is not typ or not v for v in value.values()):
            errors.append('Invalid mapping decision field: '+key)
            decisions={k:v for k,v in decisions.items() if k!=key}
    if spec.get('status')!='PASS': errors.append('Specification interface extraction must be PASS')
    if spec.get('direction_reference','DUT')!='DUT': errors.append('Specification directions must be relative to DUT')
    if definition.get('direction_reference','DUT')!='DUT': errors.append('RTL directions must be relative to DUT')
    signals=spec.get('signals') or [p for g in spec.get('groups',[]) for p in g.get('signals',[])]
    rtl=definition.get('ports',[])
    if not signals or not rtl: errors.append('Both independently extracted port inventories are required')
    if len({p['name'] for p in rtl})!=len(rtl): errors.append('Duplicate RTL port names')
    if len({p['name'] for p in signals})!=len(signals): errors.append('Duplicate specification port names')
    mappings=decisions.get('mappings',{})
    known={p['name'] for p in signals}
    for key in ('mappings','width_choices','inactive_spec_ports'):
        if set(decisions.get(key,{}))-known: errors.append('Unknown specification signal in '+key)
    norm=lambda s:re.sub(r'[^a-z0-9]','',s.lower())
    exact={p['name']:p for p in rtl}
    normalized={}
    for p in rtl: normalized.setdefault(norm(p['name']),[]).append(p)
    used=set();rows=[]
    for signal in signals:
        name=signal['name'];issues=[]
        if name in decisions.get('inactive_spec_ports',{}):
            if condition_supported(signal) and decisions['inactive_spec_ports'][name]:
                rows.append(dict(spec=name,rtl=None,status='INACTIVE_REVIEWED',reason=decisions['inactive_spec_ports'][name],source_id=signal.get('chunk_id')))
                continue
            issues.append('Only a documented conditional signal may be marked inactive with a reason')
        target=mappings.get(name)
        choices=([exact[target]] if target in exact else []) if target else normalized.get(norm(name),[])
        port=choices[0] if len(choices)==1 else None
        sw=width(signal.get('width'));rw=width(port.get('width',port.get('range'))) if port else None
        alternatives=width_options(signal.get('width'))
        if alternatives and name in decisions.get('width_choices',{}):
            choice=decisions['width_choices'][name]
            if type(choice) is int and choice in alternatives: sw=choice
        if not port: issues.append('Missing/ambiguous RTL match; provide a reviewed alias mapping')
        else:
            if port['name'] in used: issues.append('RTL port already mapped by another specification signal')
            used.add(port['name'])
            if signal.get('direction') not in ('input','output','inout') or signal.get('direction_documented') is False:
                issues.append('Specification direction is unresolved')
            elif signal['direction']!=port['direction']: issues.append('DUT-relative direction mismatch')
            if sw is None or rw is None or signal.get('width_documented') is False: issues.append('Width or configuration-dependent width is unresolved')
            elif sw!=rw: issues.append('Width mismatch')
        rows.append(dict(spec=name,rtl=port['name'] if port else target,spec_direction=signal.get('direction'),
                         rtl_direction=port.get('direction') if port else None,spec_width=sw,rtl_width=rw,
                         status='BLOCKED' if issues else 'PASS',issues=issues,source_id=signal.get('chunk_id'),
                         availability=signal.get('availability',''),reviewed_alias=name in mappings))
    extras=[p['name'] for p in rtl if p['name'] not in used]
    if extras: errors.append('RTL ports missing from specification inventory: '+', '.join(extras))
    from .interface_context import relationships
    report=dict(status='BLOCKED' if errors or any(r['status']=='BLOCKED' for r in rows) else 'PASS',
                **hashes,direction_reference='DUT',rows=rows,errors=errors,unmatched_rtl=extras,
                review_decisions=decisions,relationship_context=relationships(plan,definition,rows))
    if validate:
        from .port_validation import attach_validation
        attach_validation(plan,definition,report,decisions)
    return report


def recheck_conditions(plan, out):
    """Quick testing only: a saved plan may have marked a port's condition undocumented over its wording. Check again against the saved source."""
    from ..quality.quick_testing import enabled
    if not (enabled() and plan.get('test_only') and (out/'quick_testing.json').is_file() and (out/'dv/chunks.jsonl').is_file()): return []
    interfaces=plan.get('interfaces') or {}
    signals=list(interfaces.get('signals') or [])+[s for g in interfaces.get('groups',[]) for s in g.get('signals',[])]
    pending=[s for s in signals if s.get('availability') and s.get('documented',{}).get('availability') is False]
    if not pending: return []
    sources={}
    for line in (out/'dv/chunks.jsonl').read_text().splitlines():
        chunk=json.loads(line);sources[chunk.get('chunk_id')]=chunk.get('text','')
    confirmed=[s for s in pending if condition_stated(sources.get(s.get('chunk_id'),''),s['availability'])]
    for s in confirmed: s['documented']['availability']=True
    if confirmed:
        from ..quality.human_review import current_plan_path
        path=current_plan_path(out);atomic_write_text(path,json.dumps(plan,indent=2)+'\n')
    return sorted({s['name'] for s in confirmed})


def enforce(plan, definition, out, *, resolve=True):
    out=Path(out);file=out/'interface_port_mapping.json'
    rechecked=recheck_conditions(plan,out)
    if rechecked: emit('code: port conditions confirmed from the saved source: '+', '.join(rechecked))
    decisions=json.loads(file.read_text()) if file.is_file() else None
    if decisions is None:
        from .port_reconciliation import recover_decisions
        decisions=recover_decisions(plan,definition,out)
        if decisions is not None:
            from ..quality.human_review import write
            write(file,decisions)
    if decisions and decisions.get('test_only'):
        from ..quality.quick_testing import enabled
        if not enabled() or not plan.get('test_only') or not (out/'quick_testing.json').is_file():
            raise ValueError('Test-only port alignment requires an isolated quick-testing run and explicit mode')
    report=compare(plan,definition,decisions,validate=False)
    from .events import stage
    from .port_validation import attach_validation
    with stage('code_port_validation','Independently validate specification/RTL comparison') as outcome:
        attach_validation(plan,definition,report,decisions)
        outcome['status']=report['independent_validation']['status']
    audit=report['independent_validation']
    atomic_write_text(out/'interface_port_validation.json',json.dumps(audit,indent=2)+'\n')
    atomic_write_text(out/'interface_port_validation.md',
        '# Independent interface comparison validation\n\nStatus: **'+audit['status']+'**\n\n'+
        '\n'.join('- '+c for c in audit['checks'])+'\n\n'+
        '\n'.join('- '+issue for issue in audit['issues'])+'\n')
    atomic_write_text(out/'interface_port_comparison.json',json.dumps(report,indent=2)+'\n')
    lines=['# Specification / RTL port comparison','',f"Status: **{report['status']}**",'',
           f"Independent validation: **{audit['status']}** ([report](interface_port_validation.md))",'',
           '| Specification | RTL | Spec direction | RTL direction | Spec width | RTL width | Status | Issues |','|---|---|---|---|---|---|---|---|']
    for row in report['rows']:
        lines.append('| '+' | '.join(str(v).replace('|','/') for v in (row['spec'],row['rtl'],row.get('spec_direction',''),row.get('rtl_direction',''),row.get('spec_width',''),row.get('rtl_width',''),row['status'],'; '.join(row.get('issues',[])) or row.get('reason','')))+' |')
    lines+=['']+['- '+error for error in report['errors']]
    lines+=['','## Specification and RTL relationship','',report['relationship_context']['authority'],'']
    for port in report['relationship_context']['ports']:
        spec=port['specification']
        lines += [f"### {port['spec_name']} → {port['rtl_name']}", '',
                  f"- Match: {port['match_basis']}; testbench responsibility: {port['testbench_responsibility']}.",
                  f"- Specification: {spec.get('doc_path','')} {spec.get('pages',[])} / {spec.get('chunk_id','unknown')}",
                  f"- Description: {spec.get('description','not documented')}",
                  f"- Active level: {spec.get('active_level','unknown')} (documented: {spec.get('active_level_documented',False)})",'']
        if spec.get('quote'): lines += ['> '+spec['quote'].replace('\n','\n> '),'']
    for group in report['relationship_context']['groups']:
        lines += [f"### Interface group: {group['properties'].get('name',group['plan_pointer'])}",'']
        lines += [f"- **{key}**: {value} ({group['property_evidence'].get(key,{}).get('provenance','UNCONFIRMED')})" for key,value in group['properties'].items()]
        lines += [f"- Evidence and classification: `{group['plan_pointer']}/property_evidence` (retained in JSON)",'']
    atomic_write_text(out/'interface_port_comparison.md','\n'.join(lines)+'\n')
    if report['status']!='PASS':
        cause=None
        if resolve:
            from .port_reconciliation import reconcile
            cause=reconcile(plan,definition,out,report)
        raise ValueError('Spec/RTL port comparison BLOCKED; review interface_port_comparison.md before generating SV interfaces or DV collateral'
                         +(f'. Not sent for review because {cause}.' if cause else ''))
    return report
