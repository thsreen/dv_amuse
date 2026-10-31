"""Clock campaign spans bands, preserves ps timing, and feeds both plan sections."""
import json
import pytest

from dv_agent.codegen.contracts import ClockPeriodRange, Fact
from dv_agent.codegen.clock_timing import period_cases, validate_ranges
from test_codegen import inputs, build


def bands():
    return [ClockPeriodRange(name='fast',min_ps=2501,max_ps=5001,nominal_ps=3501,cited_chunk_ids=['CH-spec']),
            ClockPeriodRange(name='slow',min_ps=20000,max_ps=40000,nominal_ps=30000,cited_chunk_ids=['CH-spec'])]


def test_clock_campaign_reproducible_all_bands_boundaries_and_strata():
    ranges=bands();cases=period_cases(ranges,17)
    assert cases==period_cases(ranges,17) and cases!=period_cases(ranges,18)
    assert len(cases)==12
    for r in ranges:
        selected=[c for c in cases if c['range']==r.name]
        assert {r.min_ps,r.max_ps,r.nominal_ps} <= {c['period_ps'] for c in selected}
        for c in selected:
            assert r.min_ps<=c['period_ps']<=r.max_ps
            assert c['frequency_mhz']==1000000/c['period_ps']
        for index in range(3):
            c=next(c for c in selected if c['kind']=='random_'+str(index));count=r.max_ps-r.min_ps+1
            assert r.min_ps+index*count//3<=c['period_ps']<=r.min_ps+(index+1)*count//3-1
    assert all(not 5001<c['period_ps']<20000 for c in cases)


def test_clock_range_validation_rejects_unknown_authority_and_invalid_bounds():
    facts=[Fact(id='clock',source_id='CH-spec',quote='Clock source description',statement='Clock source',plan_pointer='/clock')]
    for change in (dict(min_ps=6000),dict(nominal_ps=999999),dict(cited_chunk_ids=['unknown']),dict(provenance='INFERRED')):
        with pytest.raises(ValueError): validate_ranges([bands()[0].model_copy(update=change)],facts)
    tiny=ClockPeriodRange(name='tiny',min_ps=2,max_ps=2,cited_chunk_ids=['CH-spec'])
    assert all(c['period_ps']==2 for c in period_cases([tiny],3))


def test_clock_manifest_and_templates_use_selected_ps_period_and_monitor_coverage(inputs):
    root,plan,definition,contract,rtl=inputs
    text=plan['sections'][0]['entries'][0]['text']+' Approved clock periods: 2501..5001 ps, nominal 3501 ps; 20000..40000 ps, nominal 30000 ps.'
    plan['sections'][0]['entries'][0]['text']=text;plan['evidence_index']['CH-spec']['excerpt']=text
    contract['facts'][0].update(quote=text,statement=text)
    contract['clock_period_ranges']=[r.model_dump() for r in bands()]
    (root/'plan.json').write_text(json.dumps(plan));(root/'contract.json').write_text(json.dumps(contract))
    manifest=build(inputs)
    assert len(manifest['tests'])==12
    assert manifest['clock_randomization']['coverage_status']=='NOT_RUN'
    from dv_agent.codegen.simulator import command
    case=manifest['tests'][0]
    args=command(manifest,dict(binary='simulator',uvm=str(root/'uvm_pkg.sv')),simulate=True,test=case)
    assert '+UVM_TESTNAME=basic_functional' in args and '+CLOCK_PERIOD_PS=2501' in args
    code=root/'output'/'code'/manifest['build_id'][:16]
    test=(code/'tests/basic_functional.svh').read_text()
    assert 'clock_control.period * 8' in test and 'CLOCK_RANGE' in test
    assert 'clock_uvc.mon.ap.connect(clock_cov.analysis_export)' in test
    assert 'realtime period' in (code/'common_uvc/clock/clock_cfg.svh').read_text()
    assert '$floor' in (code/'common_uvc/clock/clock_driver.svh').read_text()
    assert '$realtime' in (code/'common_uvc/clock/clock_monitor.svh').read_text()
    assert 'cp_period_ps' in (code/'uvm/cg_clock_coverage.svh').read_text()


def test_clock_approval_is_reflected_in_strategy_and_verification_plan(tmp_path):
    from test_human_review import seed
    from dv_agent.quality.human_review import request_review, HumanReviewPending, approve
    from dv_agent.plan.approved_clarifications import apply_approval
    run,plan,definition=seed(tmp_path)
    plan['sections'] += [dict(id='strategy',generator='strategy',heading='Strategy',status='PASS',
                             strategy=dict(status='PASS',overview=[dict(text='Verify interfaces.',provenance='INFERRED')],validation=[])),
                         dict(id='verification_plan',generator='entries',heading='Verification Plan',status='PASS',entries=[])]
    path=run/'dv/testplan_doc.json';path.write_text(json.dumps(plan))
    with pytest.raises(HumanReviewPending):
        request_review(run,plan,definition,'foundation_clock',['Clock timing limits?'],{})
    folder=next((run/'human_review').iterdir());request=json.loads((folder/'request.json').read_text())
    bindings=dict(clock='clk',clock_period_ns=3,clock_period_ranges=[dict(name='operating',min_ps=2500,max_ps=5000,nominal_ps=3000)])
    receipt=approve(folder,request['id'],request['nonce'],bindings,'Designer confirmed these test settings.',actor='42',channel='terminal',reference='tty')
    apply_approval(path,request,receipt);doc=json.loads(path.read_text())
    strategy=next(s for s in doc['sections'] if s['id']=='strategy')['strategy']
    assert strategy['clock_timing'][0]['nominal'].startswith('3 ns')
    assert strategy['clock_timing'][0]['period_ranges'][0]['min_ps']==2500
    entries=next(s for s in doc['sections'] if s['id']=='verification_plan')['entries']
    assert entries[0]['kind']=='clock_timing' and entries[0]['cited_chunk_ids']==['HUMAN-'+request['id']]
    for extension in ('md','html'):
        rendered=(run/f'dv/testplan_doc.{extension}').read_text()
        assert 'Clock Timing and Randomization' in rendered and '3 ns' in rendered


def test_natural_clock_period_preserves_fractional_nanoseconds():
    from dv_agent.quality.human_dialogue import interpret
    request=dict(allowed_fields=['clock','clock_period_ns'],ports=[dict(name='clk',direction='input',width=1)])
    assert interpret(request,'Use clk with a 3.5 ns period.')==dict(clock='clk',clock_period_ns=3.5)
    with pytest.raises(ValueError,match='1ps'):
        interpret(request,'Use a 3.5001 ns period.')
    with pytest.raises(ValueError,match='positive'):
        interpret(request,'Use clk at -3.5 ns.')


def test_numeric_range_evidence_converts_frequency_units_and_refuses_invented_limits():
    from dv_agent.codegen.clock_timing import source_periods,source_bands
    low,high=source_periods(['Clock operating frequency 20–40 MHz. Nominal is 25 MHz.'])
    assert {25000,50000,40000}<=low and {25000,50000,40000}<=high
    assert source_periods(['Clock nominal 4e7 Hz.'])==({25000},{25000})
    assert source_bands(['Clock frequency 20 MHz to 40 MHz.'])=={(25000,50000)}
    assert source_bands(['Clock period 2.5 ns to 5 ns.'])=={(2500,5000)}
    fact=Fact(id='clock',source_id='CH-spec',quote='Clock nominal 10 ns.',statement='Clock source',plan_pointer='/clock')
    with pytest.raises(ValueError,match='numeric source evidence'):
        validate_ranges(bands(),[fact])
    fact=fact.model_copy(update=dict(quote='Clock periods 2501..5001 ps, nominal 3501 ps; 20000..40000 ps.'))
    with pytest.raises(ValueError,match='bridge gaps'):
        validate_ranges([bands()[0].model_copy(update=dict(max_ps=40000))],[fact])


@pytest.mark.parametrize('observed,expected',[(None,'BLOCKED'),(2499,'FAIL'),(2500,'PASS')])
def test_simulator_requires_monitor_confirmation_of_clock_case(inputs,monkeypatch,observed,expected):
    import subprocess
    from pathlib import Path
    from dv_agent.codegen import simulator
    manifest=build(inputs);manifest['tests'][0]['clock_period_ps']=2500
    manifest['tests'][0]['clock_case']=dict(range='operating',kind='min',period_ps=2500)
    monkeypatch.setattr(simulator,'compile_project',lambda *a:dict(status='PASS',binary='sim',uvm='/tmp/uvm_pkg.sv'))
    def fake(cmd,**kwargs):
        assert '+CLOCK_PERIOD_PS=2500' in cmd
        sites=[]
        for check in manifest['assertion_covers']:
            for field,kind in [('assertion_line','assert'),('cover_line','cover'),('activation_line','cover')]:
                sites.append(dict(file=check['file'],line=check[field],kind=kind,**{'pass':1,'fail':0}))
        Path(kwargs['env']['XEZIM_COV_DB']).write_text(json.dumps(dict(assertions=sites,covergroups=[dict(name='observed',samples=1)])))
        log='[SCOREBOARD_SUMMARY] comparisons=1\nFUNCTIONAL_TEST_PASS basic_functional\n'
        if observed is not None: log+=f'CLOCK_PERIOD_OBSERVED_PS {observed}\n'
        return subprocess.CompletedProcess(cmd,0,log,'')
    monkeypatch.setattr(simulator.subprocess,'run',fake)
    result=simulator.run_project(manifest)
    assert result['tests'][0]['status']==expected
    assert result['tests'][0]['observed_clock_periods_ps']==([] if observed is None else [observed])
