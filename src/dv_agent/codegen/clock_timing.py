"""Bounded, reproducible period sampling over every approved operating band."""
import random
import re
import json
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


def source_bands(quotes):
    bands=set()
    n=r'(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)'
    u=r'(ps|ns|us|ms|Hz|kHz|MHz|GHz)'
    def ps(value,unit):
        unit=unit.lower();value=Decimal(value)
        if value<=0: return None
        return (Decimal({'hz':10**12,'khz':10**9,'mhz':10**6,'ghz':10**3}[unit])/value
                if unit.endswith('hz') else value*{'ps':1,'ns':1000,'us':10**6,'ms':10**9}[unit])
    def walk(value):
        if isinstance(value,dict):
            if type(value.get('min_ps')) is int and type(value.get('max_ps')) is int:
                bands.add((value['min_ps'],value['max_ps']))
            for child in value.values(): walk(child)
        elif isinstance(value,list):
            for child in value: walk(child)
    for quote in quotes:
        for m in re.finditer(r'(?<![\w.\-])'+n+r'\s*(?:'+u+r'\s*)?(?:\.\.|–|\bto\b|-)\s*'+n+r'\s*'+u+r'\b',quote,re.I):
            a,b=ps(m[1],m[2] or m[4]),ps(m[3],m[4])
            if a is not None and b is not None:
                bands.add((int(min(a,b).to_integral_value(rounding=ROUND_CEILING)),int(max(a,b).to_integral_value(rounding=ROUND_FLOOR))))
        for match in re.finditer(r'\{',quote):
            try: walk(json.JSONDecoder().raw_decode(quote[match.start():])[0])
            except (ValueError,TypeError): pass
    return bands


def source_periods(quotes):
    """Numeric evidence only; unitless register values cannot justify clock bounds."""
    low, high=set(),set()
    number=r'(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)'
    units=r'(ps|ns|us|ms|Hz|kHz|MHz|GHz)\b'
    for quote in quotes:
        values=[]
        for match in re.finditer(r'(?<![\w.\-])'+number+r'\s*(?:\.\.|–|\bto\b|-)\s*'+number+r'\s*'+units,quote,re.I):
            values += [(match[1],match[3]),(match[2],match[3])]
        values += [(m[1],m[2]) for m in re.finditer(r'(?<![\w.\-])'+number+r'\s*'+units,quote,re.I)]
        for match in re.finditer(r'"(?:min_ps|max_ps|nominal_ps)"\s*:\s*(\d+)',quote):
            values.append((match[1],'ps'))
        for value,unit in values:
            n=Decimal(value);unit=unit.lower()
            if n<=0: continue
            period=(Decimal({'hz':1000000000000,'khz':1000000000,'mhz':1000000,'ghz':1000}[unit])/n
                    if unit in ('hz','khz','mhz','ghz') else n*{'ps':1,'ns':1000,'us':1000000,'ms':1000000000}[unit])
            low.add(int(period.to_integral_value(rounding=ROUND_CEILING)))
            high.add(int(period.to_integral_value(rounding=ROUND_FLOOR)))
    return low,high


def reviewed_ranges(values, source_id, *, test=False, reason=''):
    from .contracts import ClockPeriodRange
    if not isinstance(values,list) or not 1<=len(values)<=16:
        raise ValueError('Specify 1..16 clock operating bands')
    result=[]
    for value in values:
        if not isinstance(value,dict) or set(value)-{'name','min_ps','max_ps','nominal_ps'}:
            raise ValueError('Clock band needs name, min_ps, max_ps and optional nominal_ps')
        r=ClockPeriodRange.model_validate(dict(value,cited_chunk_ids=[source_id],
            provenance='INFERRED' if test else 'DOCUMENTED',inference_reason=reason if test else ''))
        if r.min_ps>r.max_ps or r.nominal_ps is not None and not r.min_ps<=r.nominal_ps<=r.max_ps:
            raise ValueError('Clock nominal must lie inside ordered period bounds')
        if any(old['name']==r.name for old in result): raise ValueError('Clock band names must be unique')
        result.append(r.model_dump())
    return result


def validate_ranges(ranges, facts, *, test_only=False):
    from .contracts import identifier
    names=set()
    sources={f.source_id for f in facts}
    for r in ranges:
        identifier(r.name)
        if r.name in names: raise ValueError('Clock range names must be unique')
        names.add(r.name)
        if r.min_ps>r.max_ps or r.nominal_ps is not None and not r.min_ps<=r.nominal_ps<=r.max_ps:
            raise ValueError('Clock nominal and endpoints must lie within ordered bounds')
        if not set(r.cited_chunk_ids)<=sources: raise ValueError('Clock ranges need cited source-backed facts')
        if r.provenance!='DOCUMENTED' and not test_only:
            raise ValueError('Inferred clock operating ranges require review before normal execution')
        quotes=[f.quote for f in facts if f.source_id in r.cited_chunk_ids]
        low,high=source_periods(quotes)
        if r.min_ps not in low or r.max_ps not in high or r.nominal_ps is not None and r.nominal_ps not in low|high:
            raise ValueError('Clock range endpoints/nominal need numeric source evidence with timing units or reviewed ps fields')
        if (r.min_ps,r.max_ps) not in source_bands(quotes) and not (r.min_ps==r.max_ps and r.min_ps in low&high):
            raise ValueError('Clock operating band must be explicitly paired in a source; do not bridge gaps between separate bands')


def period_cases(ranges, seed):
    rng=random.Random(seed)
    result=[]
    for r in ranges:
        middle=r.nominal_ps if r.nominal_ps is not None else (r.min_ps+r.max_ps)//2
        for kind,value in [('min',r.min_ps),('max',r.max_ps),('nominal' if r.nominal_ps is not None else 'midpoint',middle)]:
            result.append(dict(range=r.name,kind=kind,period_ps=value,frequency_mhz=1000000/value))
        # Equal period-space strata; no random draw can enter a gap between bands.
        count=r.max_ps-r.min_ps+1
        for index in range(min(3,count)):
            strata=min(3,count)
            lo=r.min_ps+index*count//strata
            hi=r.min_ps+(index+1)*count//strata-1
            value=rng.randint(lo,hi)
            result.append(dict(range=r.name,kind='random_'+str(index),period_ps=value,frequency_mhz=1000000/value))
    return result


def expand_tests(tests, ranges):
    if not ranges: return tests
    return [dict(test,name=test['name']+'__clk_'+case['range']+'_'+case['kind'],
                 uvm_testname=test['name'],clock_period_ps=case['period_ps'],clock_case=case)
            for test in tests for case in period_cases(ranges,test['seed'])]
