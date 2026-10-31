"""Independent audit of a proposed spec/RTL alignment, without comparator helpers.

Checks the original inventories and review decisions, not the producer's PASS flag.
This validates the comparison; it is not a second specification/RTL extractor.
"""
import re
from collections import Counter

from ..quality.human_review import sha


def _bits(value):
    if type(value) is int:
        return value if value > 0 else None
    text=str(value).strip().lower()
    if re.fullmatch(r'[0-9]+(?:\s*bits?)?',text):
        count=int(re.match(r'[0-9]+',text)[0])
        return count if count > 0 else None
    if text.startswith('[') and text.endswith(']'): text=text[1:-1]
    if re.fullmatch(r'[0-9]+\s*:\s*[0-9]+',text):
        high,low=map(int,text.split(':'))
        return max(high,low)-min(high,low)+1
    return None


def _name(value):
    return ''.join(c for c in value.lower() if c in 'abcdefghijklmnopqrstuvwxyz0123456789')


def _allowed_widths(value):
    # Intentionally independent of the producer's tokenizer.
    if isinstance(value,list):
        values=value
    else:
        text=re.sub(r'\bor\b','|',str(value).strip().lower())
        if not re.fullmatch(r'[0-9]+\s*(?:(?:/|\||,\s*\|?)\s*[0-9]+\s*)+',text): return set()
        values=[int(p) for p in re.findall(r'[0-9]+',text)]
    if len(values)<2 or any(type(v) is not int or v<=0 for v in values): return set()
    return set(values)


def report_hash(report):
    return sha({k:v for k,v in report.items() if k!='independent_validation'})


def validated(report):
    """Detect changed reports at consumption; callers must also bind current inputs."""
    audit=report.get('independent_validation') or {}
    return (report.get('status')=='PASS' and audit.get('status')=='PASS'
            and audit.get('validator')=='independent_port_audit'
            and audit.get('report_hash')==report_hash(report)
            and audit.get('spec_hash')==report.get('spec_hash')
            and audit.get('rtl_hash')==report.get('rtl_hash'))


def validate_comparison(plan,definition,report,decisions=None):
    """Audit coverage, legality, widths, directions, evidence copies and provenance."""
    issues=[]
    spec=plan.get('interfaces') or {}
    trusted=decisions if decisions is not None else {}
    def check(ok,message):
        if not ok: issues.append(message)
    try:
        check(spec.get('status')=='PASS','Specification inventory is not PASS')
        check(spec.get('direction_reference','DUT')=='DUT' and definition.get('direction_reference','DUT')=='DUT',
              'Inventories must use DUT-relative directions')
        check(report.get('status')=='PASS' and not report.get('errors'),'Comparison is blocked or contains errors')
        check(report.get('direction_reference')=='DUT','Comparison direction reference is invalid')
        check(report.get('spec_hash')==sha(spec) and report.get('rtl_hash')==sha(definition),'Input snapshot hashes differ')
        check(report.get('review_decisions')==trusted,'Reported decisions differ from supplied review')
        if trusted:
            if trusted.get('test_only'):
                from ..quality.quick_testing import enabled
                check(enabled() and plan.get('test_only') is True,'Test-only alignment cannot be consumed outside quick testing')
            check(trusted.get('spec_hash')==sha(spec) and trusted.get('rtl_hash')==sha(definition),'Review snapshot is stale')
            check(isinstance(trusted.get('reviewer'),str) and bool(trusted['reviewer'].strip())
                  and isinstance(trusted.get('reason'),str) and bool(trusted['reason'].strip()),'Review needs reviewer and reason')
        groups=spec.get('groups',[])
        memberships={}
        for i,g in enumerate(groups):
            for s in g.get('signals',[]): memberships.setdefault(s['name'],[]).append(f'/interfaces/groups/{i}')
        signals=spec.get('signals') or [s for g in groups for s in g.get('signals',[])]
        rtl=definition.get('ports',[])
        check(bool(signals) and bool(rtl),'Both port inventories are required')
        snames=[s['name'] for s in signals];rnames=[p['name'] for p in rtl]
        check(all(isinstance(n,str) and bool(n.strip()) for n in snames+rnames),'Inventory has invalid port names')
        check(len(set(snames))==len(snames) and len(set(rnames))==len(rnames),'Inventory contains duplicate ports')
        mappings=trusted.get('mappings',{});choices=trusted.get('width_choices',{});inactive=trusted.get('inactive_spec_ports',{})
        for key,values,typ in [('mappings',mappings,str),('width_choices',choices,int),('inactive_spec_ports',inactive,str)]:
            check(isinstance(values,dict) and set(values)<=set(snames)
                  and all(type(v) is typ and bool(v) for v in values.values()),'Invalid reviewed '+key)
        rows=report.get('rows',[])
        check(Counter(r['spec'] for r in rows)==Counter(snames),'Reported spec port coverage is incomplete or duplicated')
        by_spec={s['name']:s for s in signals};by_rtl={p['name']:p for p in rtl}
        names_by_key={}
        for p in rtl: names_by_key.setdefault(_name(p['name']),[]).append(p['name'])
        used=[]
        for row in rows:
            name=row['spec'];signal=by_spec[name]
            check(row.get('source_id')==signal.get('chunk_id'),name+': source identity changed')
            if name in inactive:
                condition=signal.get('availability','')
                supported=bool(condition) and signal.get('documented',{}).get('availability') is not False
                if condition and not supported:
                    phrase=' '.join(condition.casefold().split());quote=' '.join(signal.get('quote','').casefold().split())
                    at=quote.find(phrase)
                    supported=at>=0 and not quote[:at].endswith(('not ','never '))
                check(supported,
                      name+': inactivity lacks documented condition')
                check(row.get('status')=='INACTIVE_REVIEWED' and row.get('rtl') is None and row.get('reason')==inactive[name],
                      name+': inactive disposition differs from review')
                continue
            target=row.get('rtl')
            check(target in by_rtl,name+': reported RTL port does not exist')
            if target not in by_rtl: continue
            port=by_rtl[target];used.append(target)
            candidates=names_by_key.get(_name(name),[])
            check(target==mappings[name] if name in mappings else candidates==[target],name+': unsupported or ambiguous identity mapping')
            check(row.get('reviewed_alias')==(name in mappings),name+': alias provenance differs')
            sw=_bits(signal.get('width'));rw=_bits(port.get('width',port.get('range')))
            if name in choices:
                alternatives=_allowed_widths(signal.get('width'))
                check(choices[name] in alternatives,
                      name+': review cannot override an unconditional or unsupported width')
                sw=choices[name]
            check(sw is not None and rw is not None and sw==rw and signal.get('width_documented') is not False,
                  name+': source widths differ or are unresolved/undocumented')
            check(type(row.get('spec_width')) is int and type(row.get('rtl_width')) is int
                  and row['spec_width']==sw and row['rtl_width']==rw,name+': reported widths differ from inventories')
            direction=signal.get('direction')
            check(direction in ('input','output','inout') and direction==port.get('direction')
                  and signal.get('direction_documented') is not False,name+': source directions differ or are undocumented')
            check(row.get('spec_direction')==direction and row.get('rtl_direction')==port.get('direction'),name+': reported direction changed')
            check(row.get('availability')==signal.get('availability',''),name+': availability changed')
            check(row.get('status')=='PASS' and row.get('issues')==[],name+': disposition is not clean PASS')
        check(Counter(used)==Counter(rnames),'RTL coverage is incomplete or many-to-one')
        check(report.get('unmatched_rtl')==[],'Unmatched RTL ports remain')

        # Audit copied semantics against original sources; do not call context builder.
        context=report.get('relationship_context') or {}
        check(set(context)=={'authority','rtl_sources','parameters','ports','groups'},'Unexpected relationship context fields')
        check(context.get('authority')=='Specification defines behavior; RTL defines physical connectivity. Alignment does not promote inferred semantics.',
              'Relationship authority boundary changed')
        check(context.get('rtl_sources')==definition.get('sources',[]) and context.get('parameters')==definition.get('parameters',[]),
              'Relationship RTL source/configuration changed')
        cp=context.get('ports',[])
        check(Counter(p['spec_name'] for p in cp)==Counter(snames),'Relationship port coverage differs')
        row_map={r['spec']:r for r in rows}
        for p in cp:
            check(set(p)=={'spec_name','rtl_name','status','match_basis','dut_direction','width','testbench_responsibility','specification','groups'},
                  'Unexpected relationship port fields')
            name=p['spec_name'];s=by_spec[name];r=row_map[name]
            copied={k:s[k] for k in ('name','description','quote','chunk_id','doc_path','pages','provenance','documented',
                                    'active_level','active_level_documented','availability') if k in s}
            check(p.get('specification')==copied,name+': relationship evidence or provenance changed')
            check(p.get('rtl_name')==r.get('rtl') and p.get('status')==r.get('status') and
                  p.get('width')==r.get('rtl_width') and p.get('dut_direction')==r.get('rtl_direction'),name+': relationship binding changed')
            responsibility={'input':'drive','output':'observe','inout':'bidirectional_ownership_required'}.get(r.get('rtl_direction'),'unresolved')
            basis='reviewed_alias' if name in mappings else 'exact_name' if name==r.get('rtl') else 'normalized_name' if r.get('status')=='PASS' else 'unresolved'
            check(p.get('testbench_responsibility')==responsibility and p.get('match_basis')==basis,name+': relationship role or mapping basis changed')
            check(p.get('groups')==memberships.get(name,[]),name+': group membership changed')
        expected_groups=[]
        for i,g in enumerate(groups):
            for member in g.get('signals',[]):
                original=by_spec.get(member['name'])
                check(original is not None,'Group references unknown spec signal: '+member['name'])
                if original is None: continue
                for key in ('direction','active_level'):
                    a=original.get(key);b=member.get(key)
                    if a not in (None,'unknown') and b not in (None,'unknown'):
                        check(a==b,member['name']+': group '+key+' contradicts spec inventory')
                a=_bits(original.get('width'));b=_bits(member.get('width'))
                if a is not None and b is not None: check(a==b,member['name']+': group width contradicts spec inventory')
            expected_groups.append(dict(plan_pointer=f'/interfaces/groups/{i}',properties={k:g[k] for k in
                ('name','category','function','protocol','dut_role','connected_to','peer_type','is_sideband') if k in g},
                property_evidence=g.get('property_evidence',{}),spec_signals=[s['name'] for s in g.get('signals',[])]))
        check(context.get('groups')==expected_groups,'Relationship group semantics/evidence differ from specification')
    except (KeyError,TypeError,ValueError,AttributeError) as exc:
        issues.append('Malformed comparison or input: '+type(exc).__name__)
    return dict(validator='independent_port_audit',status='BLOCKED' if issues else 'PASS',
                spec_hash=sha(spec),rtl_hash=sha(definition),report_hash=report_hash(report),issues=issues,
                checks=['inventory completeness','one-to-one identity','DUT directions','independent width evaluation',
                        'review scope and snapshots','source and provenance preservation','relationship consistency'])


def attach_validation(plan,definition,report,decisions=None):
    audit=validate_comparison(plan,definition,report,decisions)
    if audit['status']!='PASS': report['status']='BLOCKED'
    audit['report_hash']=report_hash(report)
    report['independent_validation']=audit
    return report
