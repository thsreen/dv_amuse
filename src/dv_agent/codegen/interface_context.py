"""Reusable navigation from independent specification evidence to aligned physical ports."""
from copy import deepcopy
from ..quality.human_review import sha


def relationships(plan, definition, rows):
    groups=[]
    for i,group in enumerate((plan.get('interfaces') or {}).get('groups',[])):
        groups.append(dict(plan_pointer=f'/interfaces/groups/{i}',
            properties={k:deepcopy(group[k]) for k in
                        ('name','category','function','protocol','dut_role','connected_to','peer_type','is_sideband') if k in group},
            property_evidence=deepcopy(group.get('property_evidence',{})),
            spec_signals=[s['name'] for s in group.get('signals',[])]))
    signals=(plan.get('interfaces') or {}).get('signals') or [s for g in (plan.get('interfaces') or {}).get('groups',[]) for s in g.get('signals',[])]
    by_name={s['name']:s for s in signals}
    memberships={}
    for g in groups:
        for name in g['spec_signals']: memberships.setdefault(name,[]).append(g['plan_pointer'])
    ports=[]
    for row in rows:
        signal=by_name[row['spec']]
        direction=row.get('rtl_direction')
        ports.append(dict(spec_name=row['spec'],rtl_name=row['rtl'],status=row['status'],
            match_basis='reviewed_alias' if row.get('reviewed_alias') else 'exact_name' if row['spec']==row['rtl'] else 'normalized_name' if row['status']=='PASS' else 'unresolved',
            dut_direction=direction,width=row.get('rtl_width'),
            testbench_responsibility={'input':'drive','output':'observe','inout':'bidirectional_ownership_required'}.get(direction,'unresolved'),
            specification={k:deepcopy(signal[k]) for k in
                ('name','description','quote','chunk_id','doc_path','pages','provenance','documented',
                 'active_level','active_level_documented','availability') if k in signal},
            groups=list(memberships.get(row['spec'],[]))))
    return dict(authority='Specification defines behavior; RTL defines physical connectivity. Alignment does not promote inferred semantics.',
                rtl_sources=deepcopy(definition.get('sources',[])),parameters=deepcopy(definition.get('parameters',[])),
                ports=ports,groups=groups)


def scoped(report, names):
    """Only passing, relevant alignment is consumable; preserve source provenance."""
    from .port_validation import validated
    if not report or not validated(report): return {}
    context=report.get('relationship_context') or {}
    names=set(names)
    ports=[p for p in context.get('ports',[]) if p['status']=='PASS' and p['rtl_name'] in names]
    groups={g for p in ports for g in p['groups']}
    decisions=report.get('review_decisions') or {}
    relevant={p['spec_name'] for p in ports}
    review={key:{k:v for k,v in decisions.get(key,{}).items() if k in relevant} for key in ('mappings','width_choices')}
    if any(review.values()): review.update(reviewer=decisions.get('reviewer'),reason=decisions.get('reason'))
    review.update({k:decisions[k] for k in ('review_status','test_only','request_id','source_id','assumptions') if k in decisions})
    result=dict(authority=context.get('authority'),spec_hash=report['spec_hash'],rtl_hash=report['rtl_hash'],review_decisions=review,
                independent_validation=dict(status='PASS',report_hash=report['independent_validation']['report_hash']),
                rtl_sources=context.get('rtl_sources',[]),parameters=context.get('parameters',[]),ports=deepcopy(ports),
                groups=[deepcopy(g) for g in context.get('groups',[]) if g['plan_pointer'] in groups])
    # Port-table quotes are often shared by every signal. Carry each quote once.
    quotes={}
    records=[p['specification'] for p in result['ports']]+[e for g in result['groups'] for e in g['property_evidence'].values()]
    for record in records:
        if record.get('quote'):
            quote=record.pop('quote');key=sha(quote)
            quotes[key]=quote;record['quote_ref']=key
    result['source_quotes']=quotes
    return result


def source_ids(context):
    ids={p['specification']['chunk_id'] for p in context.get('ports',[]) if p['specification'].get('chunk_id')}
    for group in context.get('groups',[]):
        for evidence in group['property_evidence'].values(): ids.update(evidence.get('cited_chunk_ids',[]))
    return ids


def plan_pointers(context):
    return [g['plan_pointer'] for g in context.get('groups',[])]


def quote_hints(context):
    quotes=context.get('source_quotes',{})
    hints=[]
    records=[p['specification'] for p in context.get('ports',[])]+[e for g in context.get('groups',[]) for e in g['property_evidence'].values() if e.get('provenance')=='DOCUMENTED']
    for record in records:
        quote=quotes.get(record.get('quote_ref'))
        ids=record.get('cited_chunk_ids',[]) or [record.get('chunk_id')]
        if quote: hints.extend((sid,quote) for sid in ids if sid)
    return list(dict.fromkeys(hints))


def compact(relation):
    """The identity map without the evidence text: names, directions, widths, group properties and where the evidence is.

    A request that spans the whole interface (a feature step) does not need every port's description or quote, and the
    full relation of a 19-port design is 32 KB. Evidence stays retrievable through the cited chunk ids and plan pointers.
    """
    if not relation: return relation
    ports=[dict({k:p[k] for k in ('spec_name','rtl_name','status','match_basis','dut_direction','width','testbench_responsibility','groups') if k in p},
                specification={k:p['specification'][k] for k in ('chunk_id','provenance') if k in p.get('specification',{})}) for p in relation.get('ports',[])]
    groups=[dict(plan_pointer=g['plan_pointer'],properties=g.get('properties',{}),
                 property_provenance={k:v.get('provenance') for k,v in g.get('property_evidence',{}).items()}) for g in relation.get('groups',[])]
    return dict(authority=relation.get('authority'),spec_hash=relation.get('spec_hash'),rtl_hash=relation.get('rtl_hash'),
                independent_validation=relation.get('independent_validation'),parameters=relation.get('parameters',[]),
                ports=ports,groups=groups,compacted='Evidence text omitted to fit the request; use the cited chunk ids and plan pointers.')
