"""Keep reviewed clock choices in strategy and implementation planning, not only an addendum."""


def reflect_clock_review(doc, request, receipt, source_id, comment):
    if request['unit']!='foundation_clock': return
    bindings=receipt['bindings'];period=bindings.get('clock_period_ns')
    test=receipt.get('test_only',False)
    nominal=(f"{period} ns ({1000/period:g} MHz)" if period else 'Period/frequency not confirmed by this decision')
    record=dict(clock=bindings.get('clock','Clock binding unchanged'),nominal=nominal,
                operating_ranges=[],randomization='Directed boundaries/nominal and seeded low/middle/high samples in each confirmed band.',
                change_policy='Select before reset; hold fixed throughout each test. Dynamic changes/jitter need separate source support.',
                open_questions=['Minimum/maximum operating bands are not established by a nominal testbench period. Confirm missing limits before range sampling.'],
                provenance='INFERRED' if test else 'DOCUMENTED',inference_reason=receipt['reason'] if test else '',
                cited_chunk_ids=[source_id],approval_request_id=request['id'],configuration_scope='testbench_setting')
    if bindings.get('clock_period_ranges'):
        from ..codegen.clock_timing import reviewed_ranges
        record['period_ranges']=reviewed_ranges(bindings['clock_period_ranges'],source_id,test=test,reason=receipt['reason'])
        record['operating_ranges']=[f"{r['name']}: {r['min_ps']}–{r['max_ps']} ps" for r in record['period_ranges']]
        record['open_questions']=[]
    else:
        previous=[timing for section in doc['sections'] if section['id']=='strategy'
                  for timing in section.get('strategy',{}).get('clock_timing',[])
                  if timing.get('operating_ranges') and (not bindings.get('clock') or timing.get('clock')==bindings['clock'])]
        if previous:
            prior=previous[-1]
            record['operating_ranges']=prior['operating_ranges']
            if prior.get('period_ranges'): record['period_ranges']=prior['period_ranges']
            record['open_questions']=prior.get('open_questions',[])
            record['cited_chunk_ids']=list(dict.fromkeys(record['cited_chunk_ids']+prior.get('cited_chunk_ids',[])))
            if prior.get('provenance')!='DOCUMENTED':
                record.update(provenance='INFERRED',inference_reason='Operating bands retain their earlier review-dependent status; this decision only resolves the new binding/nominal setting.')
    for section in doc['sections']:
        if section['id']=='strategy':
            strategy=section.setdefault('strategy',{})
            strategy.setdefault('clock_timing',[]).append(record)
        if section['id']=='verification_plan':
            section.setdefault('entries',[]).append(dict(text='Clock Timing and Randomization: reviewed testbench configuration',
                kind='clock_timing',provenance=record['provenance'],inference_reason=record['inference_reason'],
                cited_chunk_ids=record['cited_chunk_ids'],cited_req_ids=[],validation=[],approval_request_id=request['id'],
                clock_timing=dict(record),comments=comment,
                details=[f"Clock: {record['clock']}; nominal setting: {nominal}.",record['randomization'],
                         record['change_policy'],*record['open_questions'],
                         'Reset duration follows the selected period. Sample clock timing coverage from observed monitor edges.',comment]))
            from .document_layout import entry_subsections
            if not section.get('subsections'):
                section['subsections']=entry_subsections(section,{'clock_timing':'Clock Timing and Randomization'})
            else:
                group=next((s for s in section['subsections'] if s.get('id')=='clock_timing'),None)
                if group is None:
                    group=dict(id='clock_timing',heading='Clock Timing and Randomization',entry_indexes=[],layout='bullets')
                    section['subsections'].append(group)
                index=len(section['entries'])-1
                if index not in group['entry_indexes']: group['entry_indexes'].append(index)
