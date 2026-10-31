"""Reusable infrastructure tests: renamed DUT, typed bindings, evidence and real template artifacts."""
import json
from pathlib import Path

import pytest

from dv_agent.codegen import build_project
from dv_agent.codegen.contracts import CodePlan
from dv_agent.codegen.render import render
from dv_agent.codegen.validate import validate
from dv_agent.core.llm import FakeLLM


@pytest.fixture
def inputs(tmp_path):
    text = ("The peripheral has a positive clock and active-high reset. A slave bus uses request, cycle, "
            "write-enable, byte-select, register address and read/write data. Acknowledge completes a transfer. "
            "Register CONTROL at bus address 1 is 8-bit read/write storage and resets to zero. "
            "Bus control signals are known during transfers and held stable until acknowledge.")
    item = dict(text=text,provenance='DOCUMENTED',cited_chunk_ids=['CH-spec'],details=[])
    plan = dict(sections=[dict(id='checks',entries=[item])],evidence_index={'CH-spec':dict(excerpt=text)})
    # A phrase from the spec that feature retrieval does not rank, so these items do not crowd out feature evidence.
    QUOTE='Acknowledge completes a transfer'
    def infra(name,category,signal):
        evidence=dict(provenance='DOCUMENTED',cited_chunk_ids=['CH-spec'],quote=QUOTE,inference_reason='')
        return dict(name=name,category=category,function='Testbench '+name,cited_chunk_ids=['CH-spec'],property_evidence=dict(function=evidence),
                    signals=[dict(name=signal,direction='input',active_level='high',active_level_documented=True,
                                  quote=QUOTE,chunk_id='CH-spec')])
    # The testbench-supplied clock and reset the binding step reads (names match the JSON ports exactly).
    plan['interfaces']=dict(status='PASS',groups=[infra('timebase','clock','tick'),infra('initialisation','reset','clear')])
    names={'addr':'index','wdata':'push','rdata':'pull','sel':'lanes','we':'writing','stb':'request','cyc':'cycle','ack':'ready'}
    directions={r:'output' if r in ('rdata','ack') else 'input' for r in names}
    ports=[dict(name='tick',direction='input',width=1),dict(name='clear',direction='input',width=1)]
    ports += [dict(name=n,direction=directions[r],width=3 if r=='addr' else 8 if r in ('wdata','rdata') else 1) for r,n in names.items()]
    # Independent specification inventory for the pre-generation comparison gate.
    plan['interfaces']['signals']=[dict(p,chunk_id='CH-spec',width_documented=True,direction_documented=True) for p in ports]
    definition=dict(sources=['unit.sv'],direction_reference='DUT',parameters=[],ports=ports)
    contract=dict(top='peripheral',clock='tick',reset='clear',reset_active='high',
                  facts=[dict(id='behavior',statement=text,source_id='CH-spec',quote=text,plan_pointer='/sections/0/entries/0')],
                  agents=[dict(id='control',protocol='wishbone',bindings=names,fact_ids=['behavior'])],
                  registers=[dict(id='control_storage',agent='control',address=1,width=8,access='RW',reset=0,mask=255,fact_ids=['behavior'])],
                  sequences=[dict(id='storage_access',agent='control',purpose='Observed write/read round trip',fact_ids=['behavior'],
                                  operations=[dict(kind='write',address=1,data=165),dict(kind='read',address=1)])],
                  checks=[dict(id='control_known',agent='control',kind='known_controls',fact_ids=['behavior'])],
                  tests=[dict(id='basic_functional',stages=[['storage_access']],drain_cycles=8,fact_ids=['behavior'])])
    for name,data in (('plan.json',plan),('interface.json',definition),('contract.json',contract)):
        (tmp_path/name).write_text(json.dumps(data))
    rtl=tmp_path/'unit.sv'
    rtl.write_text('module peripheral(input tick,clear,input [2:0] index,input [7:0] push,output [7:0] pull, '
                   'input lanes,writing,request,cycle,output ready); reg [7:0] storage; '
                   'assign ready=request & cycle; assign pull=storage; '
                   'always @(posedge tick) if(clear) storage<=0; else if(ready && writing) storage<=push; endmodule\n')
    return tmp_path,plan,definition,contract,rtl


def build(inputs, **kwargs):
    root,_,_,_,rtl=inputs
    return build_project(root/'plan.json',root/'interface.json',root/'output',contract_path=root/'contract.json',
                         rtl_files=[rtl],expected_top='peripheral',compile=False,**kwargs)


def workflow_model(contract, **overrides):
    foundation=CodePlan.model_validate(contract).model_dump()
    for key in ('sequences','routes','checks','tests','hooks','coverage'): foundation[key]=[]
    facts=contract['facts']
    handlers={
        'code_grouping':lambda p:dict(understanding='Storage read/write verification',tasks=[dict(
            id='storage_feature',title='Storage access',category='feature',goal='Read/write storage control',
            plan_pointers=['/sections/0/entries/0'],depends_on=[],queries=['control storage register clock reset bus'])],questions=[]),
        'code_foundation':lambda p:foundation,
        'code_pseudocode':lambda p:dict(understanding='Write and read storage through the observed bus',
            preconditions=['Complete reset'],stimulus_steps=['Write a value, then read the same address'],
            check_steps=['Compare the observed read against the observed write'],coverage_steps=['Sample monitor transfers'],
            completion=['At least one scoreboard comparison'],facts=facts,questions=[]),
        'code_feature':lambda p:({k:contract.get(k,[]) for k in ('facts','sequences','routes','checks','hooks','coverage','questions')} |
            dict(step_implementations=[dict(step='stimulus_steps/0',component_ids=[contract['sequences'][0]['id']],question=''),
                dict(step='check_steps/0',component_ids=[contract['registers'][0]['id']],question=''),
                dict(step='coverage_steps/0',component_ids=[contract['agents'][0]['id']+'_coverage'],question='')])),
        'code_collation':lambda p:dict(shared_setup=['Reuse shared clock/reset and bus'],execution_order=[['storage_feature']],
            stimulus_approach=['Sequence write then read'],check_approach=['Compare observed values'],
            coverage_approach=['Subscribe to bus monitor'],questions=[]),
        'code_integration':lambda p:dict(tests=contract['tests'],questions=[]),
        'code_review':lambda p:dict(problems=[])}
    handlers.update({
        'code_infrastructure':lambda p:dict(understanding='Identify infrastructure',actions=['Bind scoped ports and configure infrastructure'],
            completion=['Port shapes and bounded configuration validate'],facts=facts,questions=[]),
        'code_interface_needs':lambda p:dict(level='full_agent' if p['task_id'] in {a['id'] for a in contract['agents']} else 'scaffold_only',
            reason='Required by documented interface responsibility',responsibilities=['Only the required interface infrastructure'],
            coverage=p['task_id'] in {a['id'] for a in contract['agents']},facts=facts),
        'code_interface_base':lambda p:dict(ports=[port['name'] for port in p['interface']['ports']],facts=facts),
        'code_clock':lambda p:dict(top=contract['top'],clock=contract['clock'],facts=facts),
        'code_reset':lambda p:dict(reset=contract['reset'],reset_active=contract['reset_active'],facts=facts),
        'code_interfaces':lambda p:dict(interfaces=[dict(id=a['id'],title=a['id'],signals=list(a['bindings'].values()),
            queries=['interface clock reset register']) for a in contract['agents']]),
        'code_interface':lambda p:dict(agents=[a for a in contract['agents'] if a['id']==p['task_id'].removeprefix('collateral_')],
            registers=[r for r in contract['registers'] if r['agent']==p['task_id'].removeprefix('collateral_')],facts=facts),
        'code_dependencies':lambda p:dict(understanding='Dedicated dependency pass',dependencies=[
            dict(task_id=t['id'],requires=d['task_id'],reason=d['reason']) for t in p['tasks'] for d in t['depends_on']],questions=[]),
    })
    foundation_pseudo=handlers['code_pseudocode']
    handlers.update(overrides)
    feature_pseudo=handlers['code_pseudocode']
    handlers['code_pseudocode']=lambda p: foundation_pseudo(p) if p['task']['id'].startswith(('foundation_','interface_')) else feature_pseudo(p)
    return FakeLLM(handlers)


def test_foundation_generates_templates_coverage_and_traceability(inputs):
    result=build(inputs)
    code=Path(result['code_dir'])
    assert result['compile']['status']=='NOT_RUN' and not result['reused']
    assert build(inputs)['reused']
    cov=(code/'uvm/control_coverage.svh').read_text()
    assert 'extends uvm_subscriber' in cov and 'tr.clone()' in cov and 'transactions.sample()' in cov
    assert 'cfg.vif' not in cov
    assert 'mon.ap.connect(cov.analysis_export)' in (code/'uvm/control_agent.svh').read_text()
    assert 'control.mon.ap.connect(sb.analysis_export)' in (code/'uvm/cg_env.svh').read_text()
    assert 'p_sequencer' not in (code/'sequences/storage_access.svh').read_text()
    vseq=(code/'sequences/basic_functional_vseq.svh').read_text()
    assert '.start(control_sqr)' in vseq and '.vif' not in vseq and '@(' not in vseq
    pkg=(code/'peripheral_verification_pkg.sv').read_text()
    assert 'class ' not in pkg and pkg.index('cg_item')<pkg.index('control_driver')<pkg.index('cg_env')
    assertions=(code/'checks/control_assertions.sv').read_text()
    assert 'assert property(p_control_known)' in assertions and 'cover property(p_control_known)' in assertions
    assert 'activation_control_known' in assertions
    assert '@(posedge bus.clk)' in assertions
    top=(code/'verification_top.sv').read_text()
    assert top.index('wire [7:0] dut_push;')<top.index('assign dut_push')
    assert '{{' not in '\n'.join(p.read_text() for p in code.rglob('*.svh'))
    assert (code/'traceability.json').is_file() and (code/'code_plan.json').is_file()


@pytest.mark.parametrize('failure',['inferred','quote','direction','owner','value','sequencer','self_compare'])
def test_contract_rejects_unreliable_generation(inputs,failure):
    _,spec,definition,raw,_=inputs
    if failure=='inferred': spec['sections'][0]['entries'][0]['provenance']='INFERRED'
    if failure=='quote': raw['facts'][0]['quote']='Invented source support.'
    if failure=='direction': definition['ports'][2]['direction']='output'
    if failure=='owner': raw['agents'].append(raw['agents'][0] | {'id':'duplicate_driver'})
    if failure=='value': raw['sequences'][0]['operations'][0]['data']=256
    if failure=='sequencer': raw['tests'][0]['stages']=[['storage_access','storage_access']]
    if failure=='self_compare': raw['routes']=[dict(id='tautology',expected_agent='control',actual_agent='control',
        expected_event='write',actual_event='write',fact_ids=['behavior'])]
    with pytest.raises(ValueError): validate(CodePlan.model_validate(raw),spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']})


def test_model_design_and_review_checkpoint_without_extra_calls(inputs):
    root,spec,definition,contract,rtl=inputs
    llm=workflow_model(contract)
    for _ in range(2):
        build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[rtl],compile=False)
    assert [name for name,_ in llm.calls]==[
        'code_interfaces','code_infrastructure','code_interface_base','code_interface_needs','code_infrastructure','code_interface','code_grouping','code_dependencies',
        'code_pseudocode','code_feature','code_collation','code_integration','code_review']
    assert (root/'output/contract_review.json').is_file()


def test_changed_source_changes_build_and_edits_are_protected(inputs):
    root,_,_,_,rtl=inputs
    first=build(inputs)
    rtl.write_text(rtl.read_text()+'// source revision\n')
    second=build(inputs)
    assert first['build_id']!=second['build_id']
    target=Path(second['code_dir'])/'uvm/control_driver.svh'
    target.write_text(target.read_text()+'// user edit\n')
    with pytest.raises(ValueError,match='edited'): build(inputs)


def test_custom_hooks_cannot_drive_from_monitor_or_run_external_commands(inputs):
    from dv_agent.codegen.contracts import Hook
    from dv_agent.codegen.reasoning import check_hook
    plan=CodePlan.model_validate(inputs[3])
    hook=Hook(id='observe',target='control',slot='monitor.body',purpose='observe',fact_ids=['behavior'])
    for code in ('cfg.vif.we = 1;', '$system("bad");', '`include "bad.svh"', 'class injected; endclass'):
        with pytest.raises(ValueError): check_hook(code,hook,plan)
    # Allow-list, not deny-list: file, memory, dump and simulation-control calls are all refused.
    for call in ('$fdisplay(1,"x");','$writememh("f",m);','$dumpfile("x.vcd");','$finish;','$value$plusargs("A=%d",v);','$fscanf(f,"%d",v);'):
        with pytest.raises(ValueError,match='allowed system function'): check_hook(call,hook,plan)
    assert check_hook('x = $isunknown(cfg.vif.we) ? 0 : $countones(v); `uvm_info("t",$sformatf("$%0d",x),UVM_LOW)',hook,plan)


def test_codegen_lock_refuses_overlapping_writers(inputs):
    from dv_agent.codegen.build import project_lock
    root=inputs[0]/'output'
    with project_lock(root):
        with pytest.raises(ValueError,match='already running'): build(inputs)


def test_simulator_requires_compile_and_real_success_evidence(inputs,tmp_path,monkeypatch):
    import subprocess
    from dv_agent.codegen.simulator import run_project
    manifest=build(inputs)
    binary=tmp_path/'xezim'; binary.write_text('stub')
    uvm=tmp_path/'uvm'; uvm.mkdir(); (uvm/'uvm_pkg.sv').write_text('stub'); (uvm/'uvm_macros.svh').write_text('stub')
    monkeypatch.setenv('XEZIM_BIN',str(binary)); monkeypatch.setenv('XEZIM_UVM_DIR',str(uvm))
    failed=[False]
    def fake(cmd,**kwargs):
        if '-V' in cmd: return subprocess.CompletedProcess(cmd,0,'version fixture','')
        if '--help' in cmd: return subprocess.CompletedProcess(cmd,0,'--compile --simulate --error-exit','')
        if '--compile' in cmd: return subprocess.CompletedProcess(cmd,0,'compiled','')
        assert '-I' in cmd and '+UVM_TESTNAME=basic_functional' in cmd and '+seed=1' in cmd
        sites=[]
        for check in manifest['assertion_covers']:
            sites += [dict(file=check['file'],line=check['assertion_line'],kind='assert',**{'pass':1,'fail':0}),
                      dict(file=check['file'],line=check['cover_line'],kind='cover',**{'pass':1,'fail':0}),
                      dict(file=check['file'],line=check['activation_line'],kind='cover',**{'pass':1,'fail':0})]
        Path(kwargs['env']['XEZIM_COV_DB']).write_text(json.dumps(dict(assertions=sites,covergroups=[dict(name='transactions',samples=2)])))
        log='[SCOREBOARD_SUMMARY] comparisons=1\nFUNCTIONAL_TEST_PASS basic_functional\nUVM_ERROR : 0\nUVM_FATAL : 0\n'
        if failed[0]: log+='UVM_ERROR @ 10: mismatch\n'
        return subprocess.CompletedProcess(cmd,0,log,'')
    monkeypatch.setattr('dv_agent.codegen.simulator.subprocess.run',fake)
    assert run_project(manifest)['status']=='PASS'
    failed[0]=True
    assert run_project(manifest)['status']=='FAIL'


def test_generated_systemverilog_parses_with_local_xezim(inputs):
    import shutil
    import subprocess
    binary=Path(__file__).resolve().parents[1]/'.e2e-bin/xezim'
    if not binary.is_file(): pytest.skip('Local Xezim unavailable for syntax-only test')
    result=build(inputs)
    code=Path(result['code_dir'])
    macros=Path(__file__).parent/'fixtures/codegen'
    cmd=[str(binary),'--parse','-I',str(macros),'-I',str(code),
         '-I',str(code/'common_uvc/clock'),'-I',str(code/'common_uvc/reset')]
    cmd += [str(code/name) for name in result['compile_files']]
    completed=subprocess.run(cmd,text=True,capture_output=True,timeout=30)
    assert completed.returncode==0, completed.stdout+completed.stderr


def test_contract_repair_is_bounded_and_receives_feedback(inputs):
    root,_,_,contract,rtl=inputs
    calls=[]
    def answer(payload):
        calls.append(payload)
        valid=workflow_model(contract).handlers['code_feature'](payload)
        invalid=json.loads(json.dumps(valid))
        invalid['sequences'][0]['operations'][0]['data']=256
        return valid if payload.get('repair_feedback') else invalid
    llm=workflow_model(contract,code_feature=answer)
    result=build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[rtl],compile=False)
    assert result['tests'] and len(calls)==2
    assert 'exceeds' in calls[1]['repair_feedback']
    assert (root/'output/code_work_manifest.json').is_file()


def test_uart_acceptance_uses_same_generic_templates_and_parses(tmp_path):
    import subprocess
    from codegen_uart_fixture import create
    try: repo=create(tmp_path)
    except FileNotFoundError as exc: pytest.skip(str(exc))
    manifest=build_project(tmp_path/'testplan.json',tmp_path/'interface.json',tmp_path/'output',
                           contract_path=tmp_path/'code_contract.json',
                           rtl_files=list((repo/'rtl/verilog').glob('*.v')),compile=False)
    assert [t['name'] for t in manifest['tests']]==['basic_functional','random_transmit']
    assert len(manifest['coverage_collectors'])==3
    code=Path(manifest['code_dir'])
    scoreboard=(code/'uvm/cg_scoreboard.svh').read_text()
    assert 'qualification_transmit_path' in scoreboard
    assert 'expected_transmit_path.push_back' in scoreboard and 'actual_receive_path.push_back' in scoreboard
    assert 'ap.write(tr)' in (code/'uvm/serial_link_monitor.svh').read_text()
    assert 'req.kind!=6' in (code/'uvm/register_bus_driver.svh').read_text()
    binary=Path(__file__).resolve().parents[1]/'.e2e-bin/xezim'
    if not binary.is_file(): pytest.skip('Generated UART artifacts; local syntax tool unavailable')
    cmd=[str(binary),'--parse','-I',str(Path(__file__).parent/'fixtures/codegen'),'-I',str(code),
         '-I',str(code/'common_uvc/clock'),'-I',str(code/'common_uvc/reset')]
    completed=subprocess.run(cmd+[str(code/name) for name in manifest['compile_files']],
                             text=True,capture_output=True,timeout=30)
    assert completed.returncode==0, completed.stdout+completed.stderr


def test_compiler_repairs_only_declared_hook_once(inputs,monkeypatch):
    root,_,_,contract,rtl=inputs
    contract['hooks']=[dict(id='classification',target='control',slot='coverage.sample',
                            purpose='classify observed data',fact_ids=['behavior'])]
    (root/'contract.json').write_text(json.dumps(contract))
    requests=[]; compilations=[]
    def hook(payload):
        requests.append(payload)
        return {'code':'data_class=2;' if payload.get('repair_feedback') else 'data_class=invalid_identifier;'}
    llm=FakeLLM({'code_review':lambda payload:{'problems':[]},'code_hook':hook})
    def compile_code(manifest):
        compilations.append(manifest)
        log=Path(manifest['code_dir'])/'compile.log'
        log.write_text('control_coverage.svh:25: unknown identifier invalid_identifier\n')
        return dict(status='FAIL' if len(compilations)==1 else 'PASS',log=str(log))
    monkeypatch.setattr('dv_agent.codegen.build.compile_project',compile_code)
    manifest=build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,
                           contract_path=root/'contract.json',rtl_files=[rtl],compile=True)
    assert manifest['compile']['status']=='PASS' and len(compilations)==2 and len(requests)==2
    assert 'compiler_diagnostics' in requests[1]['repair_feedback']
    assert compilations[0]['build_id']!=compilations[1]['build_id']
    assert (Path(compilations[0]['code_dir'])/'failed_compile_manifest.json').is_file()


def test_changed_plan_and_failed_rebuild_cannot_run_previous_collateral(inputs):
    from dv_agent.codegen.simulator import compile_project
    from orchestrator_agent.actions import run_tests
    root,_,_,contract,_=inputs
    manifest=build(inputs)
    (root/'plan.json').write_text((root/'plan.json').read_text()+'\n')
    assert compile_project(manifest)['status']=='BLOCKED'
    contract['sequences'][0]['operations'][0]['data']=256
    (root/'contract.json').write_text(json.dumps(contract))
    with pytest.raises(ValueError): build(inputs)
    assert run_tests(root/'output')['status']=='BLOCKED'


def test_model_connection_failure_is_recoverable_and_sanitized(inputs):
    from dv_agent.core.llm import LLMError
    root,_,_,_,rtl=inputs
    def fail(payload): raise LLMError('transient','provider detail must not be persisted')
    llm=workflow_model(inputs[3],code_grouping=fail)
    with pytest.raises(ValueError,match='retry /code'):
        build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[rtl],compile=False)
    report=(root/'output/code_questions.json').read_text()
    assert 'transient' in report and 'provider detail' not in report


def test_run_code_cli_replays_saved_project_without_model_and_blocks_failed_rebuild(inputs,monkeypatch,capsys):
    from dv_agent.cli import main
    root=inputs[0]
    build(inputs)
    calls=[]
    def run(manifest,**kwargs):
        calls.append(kwargs)
        return dict(status='PASS',tests=[])
    monkeypatch.setattr('dv_agent.codegen.simulator.run_project',run)
    args=['run-code','--out',str(root/'output'),'--regress','--timeout','60']
    assert main(args)==0
    assert json.loads(capsys.readouterr().out)['status']=='PASS'
    assert calls==[dict(regress=True,timeout=60)]
    (root/'output/code_generation_state.json').write_text(json.dumps(dict(status='BLOCKED')))
    assert main(args)==1
    assert json.loads(capsys.readouterr().out)['status']=='BLOCKED' and len(calls)==1


def test_code_design_compacts_nested_records_and_keeps_complete_sources(inputs):
    from dv_agent.codegen.build import load_sources
    from dv_agent.codegen.reasoning import compact_items,eligible_items
    from dv_agent.codegen.workplan import Evidence
    root,spec,definition,contract,_=inputs
    source=spec['evidence_index']['CH-spec']['excerpt']+' Source padding.'*800
    spec['evidence_index']['CH-spec']['excerpt']=source
    support=dict(provenance='DOCUMENTED',sources=[dict(chunk_id='CH-spec',quote=source)],quote=source)
    spec['registers']=dict(registers=[dict(**support,name='CONTROL',address='1',width='8',
        documented=dict(width=True,reset_value=False),configuration=dict(provenance='INFERRED',configurable=True),fields=[
        dict(**support,name='FIELD_'+str(i),bits='0',access='RW',description='Documented field') for i in range(60)])])
    spec['interfaces']=dict(groups=[dict(name='control_bus',function='Register access',
        property_evidence=dict(function=dict(provenance='DOCUMENTED',cited_chunk_ids=['CH-spec'],quote=source)))])
    sources=load_sources(spec)
    assert len(json.dumps(eligible_items(spec,sources)))>160000
    payload=dict(documented_items=compact_items(eligible_items(spec,sources),spec))
    register=next(i for i in payload['documented_items'] if i['plan_pointer']=='/registers/registers/0')
    assert register['item']['fields'][0]['plan_pointer']=='/registers/registers/0/fields/0'
    assert register['item']['documented']['reset_value'] is False
    assert register['item']['configuration']['provenance']=='INFERRED'
    leaf=next(i for i in payload['documented_items'] if i['plan_pointer'].endswith('/fields/0'))
    assert leaf['item']['bits']=='0' and leaf['item']['access']=='RW'
    property_item=next(i for i in payload['documented_items'] if '/property_evidence/' in i['plan_pointer'])
    assert property_item['item']['value']=='Register access' and property_item['item']['subject']=='control_bus'
    selected=Evidence(spec,sources).fetch(['CONTROL storage clock reset'],item_limit=8)
    assert len(selected['documented_items'])<=8 and len(json.dumps(selected))<24000
    assert len(selected['source_excerpts'])<=8
    assert all(w['text']==sources[w['source_id']][w['start']:w['end']] for w in selected['source_excerpts'])
    assert all(len(w['text'])<=1600 for w in selected['source_excerpts'])


def test_dependency_documents_and_collated_pseudocode_precede_code(inputs):
    root,spec,_,contract,rtl=inputs
    spec['sections'][0]['entries']*=3
    (root/'plan.json').write_text(json.dumps(spec))
    tasks=[dict(id=tid,title=tid,category='feature',goal='Storage verification',
        plan_pointers=[f'/sections/0/entries/{i}'],depends_on=([dict(task_id='setup',reason='Configure before access')]
        if tid=='dependent' else []),queries=['clock reset storage register'])
        for i,tid in enumerate(['setup','dependent','independent'])]
    llm=workflow_model(contract,
        code_grouping=lambda p:dict(understanding='Shared setup, storage access, independent observation',tasks=tasks,questions=[]),
        code_collation=lambda p:dict(shared_setup=['Reuse reset and bus configuration'],
            execution_order=[['independent','setup'],['dependent']],stimulus_approach=['Configure before access'],
            check_approach=['Compare observed values'],coverage_approach=['Sample monitor transfers'],questions=[]))
    result=build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[rtl],compile=False)
    manifest=json.loads((root/'output/code_work_manifest.json').read_text());work=Path(manifest['work_dir'])
    deps=json.loads((work/'dependencies.json').read_text())
    assert deps['generation_waves']==[['independent','setup'],['dependent']]
    assert deps['independent']['dependent']==['independent']
    assert 'Configure before access' in (work/'dependent.md').read_text()
    assert (work/'COLLATED_PSEUDOCODE.md').is_file() and (work/'collated_understanding.json').is_file()
    names=[name for name,_ in llm.calls]
    assert names.index('code_feature') < max(i for i,n in enumerate(names) if n=='code_pseudocode') < names.index('code_collation')
    for name,payload in llm.calls:
        if name=='code_feature': assert 'dependency_handling' in payload and 'pseudocode' in payload
        assert len(json.dumps(payload))<48000
    assert result['work_documents']==str(root/'output/code_work_manifest.json')
    assert manifest['status']=='COMPLETE_NEEDS_REVIEW'


def test_dependency_cycles_and_omissions_are_refused():
    from dv_agent.codegen.workplan import WorkGraph,dependency_waves
    def task(tid,ref,dep): return dict(id=tid,title=tid,category='feature',goal=tid,plan_pointers=[ref],
        depends_on=[dict(task_id=dep,reason='Required setup')],queries=[tid])
    g=WorkGraph.model_validate(dict(understanding='Cyclic',tasks=[task('a','/a','b'),task('b','/b','a')],questions=[]))
    with pytest.raises(ValueError,match='Cyclic'): dependency_waves(g,{'/a','/b'})
    with pytest.raises(ValueError,match='Every plan intention'): dependency_waves(g,{'/a','/b','/c'})


def test_pseudocode_only_batches_inventory_and_collates_cross_batch_dependencies(inputs):
    from dv_agent.codegen.workplan import design
    from dv_agent.codegen.build import load_sources
    root,spec,definition,contract,_=inputs
    spec['sections'][0]['entries']=[dict(spec['sections'][0]['entries'][0],text='Storage access '+('detail '*70)) for _ in range(50)]
    def groups(payload):
        items=payload['intentions'];batch=payload['batch']
        return dict(understanding='Grouped storage features',tasks=[dict(id=f'b{batch}_t{i//2}',title='Storage group',
            category='feature',goal='Storage access',plan_pointers=[e['plan_pointer'] for e in items[i:i+2]],
            depends_on=[],queries=['storage clock reset bus']) for i in range(0,len(items),2)],questions=[])
    def collate(payload):
        pending={t['id']:set(t['requires']) for t in payload['dependencies']};seen=set();order=[]
        while pending:
            ready=sorted(t for t,deps in pending.items() if deps<=seen)
            assert ready
            order.append(ready);seen.update(ready)
            for t in ready: pending.pop(t)
        return dict(shared_setup=['Shared setup'],execution_order=order,stimulus_approach=['Sequence access'],
                    check_approach=['Compare observations'],coverage_approach=['Monitor sampling'],questions=[])
    def forbidden(payload): pytest.fail('Pseudocode-only operation must not generate code')
    llm=workflow_model(contract,code_grouping=groups,code_collation=collate,code_foundation=forbidden,
        code_feature=forbidden,code_integration=forbidden,
        code_dependencies=lambda p:dict(understanding='Cross-batch setup dependency',
            dependencies=[dict(task_id='b1_t0',requires='b0_t0',reason='Reuse configuration')],questions=[]))
    result=design(llm,spec,definition,load_sources(spec),root,pseudocode_only=True)
    assert result['status']=='PSEUDOCODE_READY_NEEDS_REVIEW' and result['pseudocode_tasks'] and not result['completed_tasks']
    assert len([n for n,p in llm.calls if n=='code_grouping'])>=2
    assert 'code_dependencies' in [n for n,p in llm.calls]
    deps=json.loads((Path(result['work_dir'])/'dependencies.json').read_text())
    assert any(d['task_id']=='b0_t0' for t in deps['tasks'] if t['id']=='b1_t0' for d in t['depends_on'])
    assert all(len(json.dumps(p))<48000 for n,p in llm.calls)
    assert not (root/'code_manifest.json').exists()


def test_plan_code_cli_stops_before_code_and_preserves_edited_work_documents(inputs,monkeypatch,capsys):
    from dv_agent import cli
    root,spec,definition,contract,_=inputs
    out=root/'saved_run';(out/'dv').mkdir(parents=True);(out/'rtl').mkdir()
    (out/'dv/testplan_doc.json').write_text(json.dumps(spec))
    (out/'rtl/interface_definition.json').write_text(json.dumps(definition))
    llm=workflow_model(contract)
    monkeypatch.setattr(cli,'_models_for',lambda mode:(llm,None))
    assert cli.main(['plan-code','--out',str(out)])==0
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='PSEUDOCODE_READY_NEEDS_REVIEW'
    assert 'code_feature' not in [n for n,p in llm.calls]
    assert [n for n,p in llm.calls][-3:]==['code_dependencies','code_pseudocode','code_collation']
    assert not (out/'code_manifest.json').exists()
    document=Path(result['work_dir'])/'storage_feature.md'
    document.write_text(document.read_text()+'\nEngineer review note\n')
    assert cli.main(['plan-code','--out',str(out)])==2
    assert 'Work document was edited' in capsys.readouterr().err
    assert document.read_text().endswith('Engineer review note\n')


def test_pseudocode_step_cannot_silently_disappear(inputs):
    root,_,_,contract,rtl=inputs
    llm=workflow_model(contract)
    original=llm.handlers['code_feature']
    def omit(payload):
        result=original(payload);result['step_implementations']=[];return result
    llm.handlers['code_feature']=omit
    with pytest.raises(ValueError,match='Every pseudocode step'):
        build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[rtl],compile=False)
    assert len([n for n,p in llm.calls if n=='code_feature'])==2
    manifest=json.loads((root/'output/code_work_manifest.json').read_text())
    assert (Path(manifest['work_dir'])/'storage_feature.pseudocode.json').is_file()
    assert not (Path(manifest['work_dir'])/'COLLATED_PSEUDOCODE.md').exists()


def test_integrated_test_cannot_start_a_dependent_feature_before_setup(inputs):
    root,spec,_,contract,rtl=inputs
    spec['sections'][0]['entries']*=2
    (root/'plan.json').write_text(json.dumps(spec))
    tasks=[dict(id=tid,title=tid,category='feature',goal='Storage access',plan_pointers=[f'/sections/0/entries/{i}'],
        depends_on=[dict(task_id='setup',reason='Configure storage first')] if tid=='dependent' else [],
        queries=['storage reset clock']) for i,tid in enumerate(['setup','dependent'])]
    base=workflow_model(contract).handlers['code_feature']
    def feature(payload):
        result=base(payload);name=payload['task_id']+'_access'
        result=json.loads(json.dumps(result));result['sequences'][0]['id']=name
        result['step_implementations'][0]['component_ids']=[name]
        return result
    tests=json.loads(json.dumps(contract['tests']));tests[0]['stages']=[['dependent_access']]
    llm=workflow_model(contract,code_grouping=lambda p:dict(understanding='Setup then access',tasks=tasks,questions=[]),
        code_collation=lambda p:dict(shared_setup=['Reset/setup'],execution_order=[['setup'],['dependent']],
            stimulus_approach=['Setup before access'],check_approach=['Compare transfers'],coverage_approach=['Monitor'],questions=[]),
        code_feature=feature,code_integration=lambda p:dict(tests=tests,questions=[]))
    with pytest.raises(ValueError,match='before dependency setup'):
        build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[rtl],compile=False)


def test_specific_plan_coverage_is_monitor_fed_and_source_linked(inputs):
    root,_,_,contract,_=inputs
    contract['coverage']=[dict(id='storage_bins',agent='control',fact_ids=['behavior'],sample_kinds=[1,2],sample_address=1,
        points=[dict(name='payload',field='data',mask=255,bins=[dict(name='zero',values=[0]),dict(name='pattern',values=[165])]),
                dict(name='operation',field='kind',mask=3,bins=[dict(name='write',values=[1]),dict(name='read',values=[2])])],
        crosses=[dict(name='operation_payload',points=['operation','payload'])])]
    (root/'contract.json').write_text(json.dumps(contract))
    result=build(inputs);code=Path(result['code_dir'])
    coverage=(code/'uvm/storage_bins_coverage.svh').read_text()
    assert 'tr.clone()' in coverage and 'observed.data' in coverage and 'sampled_payload' in coverage
    assert 'operation_payload: cross operation, payload' in coverage
    assert 'control.mon.ap.connect(plan_cov_storage_bins.analysis_export)' in (code/'uvm/cg_env.svh').read_text()
    assert any(c['id']=='storage_bins' for c in result['coverage_collectors'])


def test_real_uart_simulation_opt_in(tmp_path,monkeypatch):
    import os
    if os.getenv('DV_AGENT_TEST_SIMULATION')!='1': pytest.skip('Set DV_AGENT_TEST_SIMULATION=1 for real Xezim/UVM integration')
    from dv_agent.codegen.simulator import discover, run_project
    from codegen_uart_fixture import create
    if not os.getenv('XEZIM_UVM_DIR'):
        monkeypatch.setenv('XEZIM_UVM_DIR',str(Path(__file__).resolve().parents[1]/'.deps/uvm-core-2020.3.1/src'))
    capability=discover()
    if capability['status']!='PASS': pytest.fail(str(capability))
    repo=create(tmp_path)
    contract=json.loads((tmp_path/'code_contract.json').read_text())
    contract['coverage']=[dict(id='line_format',agent='register_bus',fact_ids=['fact_2'],sample_kinds=[1,2],sample_address=3,
        points=[dict(name='word_length',field='data',mask=3,bins=[dict(name='eight_bits',values=[3])]),
                dict(name='access',field='kind',mask=3,bins=[dict(name='writes',values=[1]),dict(name='reads',values=[2])])],
        crosses=[dict(name='access_format',points=['access','word_length'])])]
    (tmp_path/'code_contract.json').write_text(json.dumps(contract))
    manifest=build_project(tmp_path/'testplan.json',tmp_path/'interface.json',tmp_path/'output',
                           contract_path=tmp_path/'code_contract.json',rtl_files=list((repo/'rtl/verilog').glob('*.v')),compile=True)  # generation defers compilation by default
    assert manifest['compile']['status']=='PASS'
    result=run_project(manifest,regress=True,timeout=60)
    assert result['status']=='PASS', [(t['name'],t['reason'],t['log']) for t in result['tests']]
    assert [t['scoreboard_comparisons'] for t in result['tests']]==[3,4]
    assert all(t['uvm_counts']['ERROR']==0 and t['uvm_counts']['FATAL']==0 for t in result['tests'])
    assert all(t['assertion_results'][0]['activation_hits']>0 for t in result['tests'])
    assert all(any('line_format_coverage' in c['name'] and c['samples']>=2 for c in t['coverage']['data']['covergroups'])
               for t in result['tests'])


def test_workflow_emits_real_feature_phases_in_execution_order(inputs):
    from dv_agent.core.progress import reporting
    root, _, _, contract, rtl = inputs
    events = []
    with reporting(event_sink=events.append):
        build_project(root/'plan.json', root/'interface.json', root/'output',
                      llm=workflow_model(contract), rtl_files=[rtl], compile=False)
    starts = [e['id'] for e in events if e['kind']=='substep_start']
    assert starts == ['code_port_comparison','code_port_validation','code_binding','code_common','code_interfaces',
        'code_infrastructure:interface_control','code_interface_base:interface_control',
        'code_interface_needs:control','code_infrastructure:collateral_control','code_interface:collateral_control',
        'code_grouping','code_dependencies','code_pseudocode:storage_feature',
        'code_feature:storage_feature','code_collation','code_integration',
        'code_validation','code_review','code_hooks','code_render','code_publish']
    configured = [e['steps'] for e in events if e['kind']=='substeps_configured'][-1]
    assert any(s['label']=='Understand Storage access' for s in configured)
    assert not any(e.get('id')=='code_compile' for e in events)
    assert (root/'output/code_manifest.json').is_file()


def test_interrupted_generation_blocks_old_manifest_until_rebuilt(inputs, monkeypatch):
    import dv_agent.codegen.build as builder
    root, _, _, _, _ = inputs
    build(inputs)
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(builder, '_build', interrupt)
    with pytest.raises(KeyboardInterrupt):
        build(inputs)
    assert json.loads((root/'output/code_generation_state.json').read_text())['status']=='BLOCKED'
    from dv_agent.codegen.simulator import run_saved_project
    assert run_saved_project(root/'output')['status']=='BLOCKED'


def test_question_only_pseudocode_recovers_targeted_evidence_before_retry(inputs):
    from dv_agent.codegen.workplan import design
    root, spec, definition, contract, _ = inputs
    llm = workflow_model(contract)
    normal = llm.handlers['code_pseudocode']
    seen = []
    def pseudo(payload):
        if payload['task']['id']!='storage_feature': return normal(payload)
        seen.append(payload)
        if len(seen) == 1:
            return dict(understanding='Need storage access details', preconditions=[], stimulus_steps=[],
                        check_steps=[], coverage_steps=[], completion=[], facts=[],
                        questions=['What is the CONTROL storage read/write contract?'])
        assert payload['evidence']['focused_recovery']
        assert 'questions alone' in payload['repair_feedback']
        assert payload['previous_pseudocode']['questions']
        assert 'Register CONTROL' in json.dumps(payload['evidence'])
        return normal(payload)
    llm.handlers['code_pseudocode'] = pseudo
    result = design(llm, spec, definition, {'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},
                    root/'output', pseudocode_only=True)
    assert result['status'] == 'PSEUDOCODE_READY_NEEDS_REVIEW' and len(seen) == 2
    assert (Path(result['work_dir'])/'storage_feature.recovery.context.json').is_file()
    assert json.loads((root/'output/code_planning_issue.json').read_text())['status'] == 'RECOVERED'


@pytest.mark.parametrize('failure', ['questions_only', 'missing_check', 'blank_step', 'no_completion', 'no_facts', 'blocker'])
def test_incomplete_pseudocode_never_becomes_ready_or_reaches_foundation(inputs, failure):
    from dv_agent.codegen.workplan import design
    root, spec, definition, contract, _ = inputs
    llm = workflow_model(contract)
    normal = llm.handlers['code_pseudocode']
    def pseudo(payload):
        data = normal(payload)
        if payload['task']['id']!='storage_feature': return data
        if failure == 'questions_only':
            for key in ('stimulus_steps', 'check_steps', 'coverage_steps'): data[key] = []
            data['questions'] = ['What is the bus contract?']
        elif failure == 'missing_check': data['check_steps'] = []
        elif failure == 'blank_step': data['check_steps'] = ['  ']
        elif failure == 'no_completion': data['completion'] = []
        elif failure == 'no_facts': data['facts'] = []
        else: data['blockers'] = ['No source-supported observable behavior for this assigned check']
        return data
    llm.handlers['code_pseudocode'] = pseudo
    with pytest.raises(ValueError):
        design(llm, spec, definition, {'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},
               root/'output', pseudocode_only=True)
    manifest = json.loads((root/'output/code_work_manifest.json').read_text())
    assert manifest['status'] == 'BLOCKED' and manifest['blocked_stage'] == 'code_pseudocode:storage_feature'
    assert len([n for n,p in llm.calls if n=='code_pseudocode' and p['task']['id']=='storage_feature']) == 2
    assert not any(n in ('code_collation','code_foundation') for n,p in llm.calls)
    assert not (Path(manifest['work_dir'])/'COLLATED_PSEUDOCODE.json').exists()
    issue = json.loads((root/'output/code_planning_issue.json').read_text())
    assert issue['status'] == 'BLOCKED' and issue['rejected_output']


def test_collation_receives_full_feature_steps_and_repairs_empty_approach(inputs):
    from dv_agent.codegen.workplan import design
    root, spec, definition, contract, _ = inputs
    llm = workflow_model(contract)
    normal = llm.handlers['code_collation']
    calls = []
    def collate(payload):
        calls.append(payload)
        feature = payload['features']['storage_feature']
        assert feature['stimulus_steps'] == ['Write a value, then read the same address']
        assert feature['check_steps'] == ['Compare the observed read against the observed write']
        assert feature['coverage_steps'] == ['Sample monitor transfers']
        assert feature['completion'] and 'facts' not in feature
        result = normal(payload)
        if len(calls)==1: result['check_approach'] = []
        else: assert 'nonempty check_approach' in payload['repair_feedback']
        return result
    llm.handlers['code_collation'] = collate
    result = design(llm, spec, definition, {'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},
                    root/'output', pseudocode_only=True)
    assert result['status'] == 'PSEUDOCODE_READY_NEEDS_REVIEW' and len(calls) == 2


def test_empty_collation_remains_blocked_after_repair(inputs):
    from dv_agent.codegen.workplan import design
    root, spec, definition, contract, _ = inputs
    llm = workflow_model(contract, code_collation=lambda p:dict(shared_setup=[],
        execution_order=[['storage_feature']],stimulus_approach=[],check_approach=[],coverage_approach=[],
        questions=['Please clarify implementation']))
    with pytest.raises(ValueError, match='nonempty shared_setup'):
        design(llm, spec, definition, {'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},
               root/'output', pseudocode_only=True)
    manifest = json.loads((root/'output/code_work_manifest.json').read_text())
    assert manifest['status']=='BLOCKED' and manifest['blocked_stage']=='code_collation'
    assert manifest['pseudocode_tasks']==['storage_feature']
    assert not (Path(manifest['work_dir'])/'COLLATED_PSEUDOCODE.json').exists()


def test_large_collation_batches_actual_steps_without_discarding_them():
    from dv_agent.codegen.workplan import Pseudocode, WorkTask, _collate
    tasks = {}; features = {}; seen = []; requests = []
    for i in range(12):
        tid = f'feature_{i}'
        tasks[tid] = WorkTask(id=tid,title=tid,category='checks',goal='Observe',
                             plan_pointers=[f'/checks/{i}'],queries=['Observe'])
        features[tid] = Pseudocode(understanding='Observe',preconditions=['Reset'],
            stimulus_steps=['Drive '+str(i)+'x'*2000],check_steps=['Compare '+str(i)+'x'*2000],
            coverage_steps=['Sample '+str(i)+'x'*2000],completion=['Terminate'],questions=[])
    def call(name, payload, model, rules, check):
        requests.append(payload)
        assert len(json.dumps(payload)) < 48000
        seen.extend(payload['features'])
        ids = [d['id'] for d in payload['dependencies']]
        result = model(shared_setup=['Reset'],execution_order=[ids],stimulus_approach=['Drive each feature'],
                       check_approach=['Compare observations'],coverage_approach=['Monitor sampling'],questions=[])
        check(result)
        return result
    approach = _collate(call, [], tasks, features)
    assert set(seen)==set(features) and len(seen)==len(features)
    assert len(requests)>2 and requests[-1]['collated_groups']
    assert set(approach.execution_order[0])==set(features)


def test_supported_check_only_feature_can_keep_nonessential_questions(inputs):
    from dv_agent.codegen.workplan import design
    root, spec, definition, contract, _ = inputs
    llm = workflow_model(contract)
    normal = llm.handlers['code_pseudocode']
    def pseudo(payload):
        result = normal(payload)
        if payload['task']['id']!='storage_feature': return result
        result.update(stimulus_steps=[], coverage_steps=[],
                      questions=['Which optional regression seeds should be used?'])
        return result
    llm.handlers['code_pseudocode'] = pseudo
    result = design(llm, spec, definition, {'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},
                    root/'output', pseudocode_only=True)
    assert result['status']=='PSEUDOCODE_READY_NEEDS_REVIEW'
    assert len([n for n,p in llm.calls if n=='code_pseudocode' and p['task']['id']=='storage_feature'])==1


def test_clock_reset_and_two_interfaces_use_identical_sequential_cycle(inputs):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    second=json.loads(json.dumps(contract['agents'][0]));second['id']='auxiliary'
    second['bindings']={role:'aux_'+name for role,name in second['bindings'].items()}
    contract['agents'].append(second)
    originals={p['name']:p for p in definition['ports']}
    definition['ports'] += [dict(originals[name],name='aux_'+name) for name in contract['agents'][0]['bindings'].values()]
    llm=workflow_model(contract)
    result=design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    assert len(result.agents)==2
    manifest=json.loads((root/'output/code_work_manifest.json').read_text());work=Path(manifest['work_dir'])
    execution=json.loads((work/'execution_plan.json').read_text())
    assert [r['id'] for r in execution['steps']]==[
        'foundation_clock','foundation_reset','interface_control','interface_auxiliary',
        'assessment_control','collateral_control','assessment_auxiliary','collateral_auxiliary','storage_feature']
    assert all(r['status']=='PASS' for r in execution['steps'])
    assert all(r['cycle']==execution['cycle'] for r in execution['steps'] if not r['id'].startswith('assessment_'))
    assert (work/'units/clock/clock_if.sv').is_file()
    assert (work/'units/reset/reset_if.sv').is_file()
    assert (work/'units/common/common_env.svh').is_file() and (work/'units/common/common_agent.svh').is_file()
    for agent in ('control','auxiliary'):
        assert (work/f'units/{agent}/uvm/{agent}_driver.svh').is_file()
        assert (work/f'units/{agent}/uvm/{agent}_monitor.svh').is_file()
    names=[n for n,p in llm.calls]
    assert 'code_clock' not in names and 'code_reset' not in names  # clock and reset are bound without the model
    assert names.index('code_interface_base')<names.index('code_interface')<names.index('code_grouping')
    assert names.count('code_dependencies')==1
    assert (work/'dependency_handling.json').is_file()



def test_missing_clock_binding_waits_for_one_decision_and_preserves_the_checkpoint(inputs):
    from dv_agent.codegen.workplan import design
    from dv_agent.quality.human_review import HumanReviewPending
    root,spec,definition,contract,_=inputs
    spec.pop('interfaces')  # nothing says which input is the clock
    llm=workflow_model(contract)
    with pytest.raises(HumanReviewPending):
        design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    assert llm.calls==[]  # no model call for clock/reset, and nothing after them started
    manifest=json.loads((root/'output/code_work_manifest.json').read_text())
    execution=json.loads((Path(manifest['work_dir'])/'execution_plan.json').read_text())
    assert execution['steps'][0]['id']=='foundation_clock' and execution['steps'][0]['status']=='WAITING_HUMAN'
    assert execution['steps'][1]['status']=='PENDING'
    request=json.loads(next((root/'output/human_review').glob('*/request.json')).read_text())
    assert request['unit']=='foundation_clock' and len(request['blockers'])==1
    assert 'tick' in request['blockers'][0] and 'clear' in request['blockers'][0]  # the candidates, nothing else


def test_code_build_defers_simulator_by_default(inputs,monkeypatch):
    root,_,_,_,rtl=inputs
    def forbidden(*a,**kw): pytest.fail('Generation must not invoke Xezim')
    monkeypatch.setattr('dv_agent.codegen.build.compile_project',forbidden)
    result=build_project(root/'plan.json',root/'interface.json',root/'output',
                         contract_path=root/'contract.json',rtl_files=[rtl])
    assert result['compile']['status']=='NOT_RUN'


def test_typed_sequence_extension_and_p_sequencer_configuration_render(inputs):
    _,spec,definition,contract,_=inputs
    contract['sequencer_variables']=[dict(id='payload_value',agent='control',width=8,default=37,fact_ids=['behavior'])]
    extended=json.loads(json.dumps(contract['sequences'][0]));extended.update(id='extended_access',extends='storage_access',
        controls=[dict(operation=0,field='data',variable='payload_value')])
    # Put the child first to verify base-before-child package ordering.
    contract['sequences'].insert(0,extended)
    contract['tests'][0]['sequencer_settings']=[dict(variable='payload_value',value=73)]
    plan=CodePlan.model_validate(contract)
    ports=validate(plan,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']})
    artifacts,_=render(plan,ports)
    assert "env.control.sqr.payload_value=64'h49;" in artifacts['tests/basic_functional.svh']
    assert 'extends storage_access' in artifacts['sequences/extended_access.svh']
    assert 'super.body();' in artifacts['sequences/extended_access.svh']
    assert '`uvm_declare_p_sequencer(control_sequencer)' in artifacts['sequences/extended_access.svh']
    assert 'tr.data=p_sequencer.payload_value;' in artifacts['sequences/extended_access.svh']
    assert "payload_value=64'h25" in artifacts['uvm/control_sequencer.svh']
    package=artifacts['peripheral_verification_pkg.sv']
    assert package.index('sequences/storage_access.svh')<package.index('sequences/extended_access.svh')


@pytest.mark.parametrize('error',['cycle','unknown_variable','width','unbounded_count'])
def test_sequence_dependency_controls_are_validated(inputs,error):
    _,spec,definition,contract,_=inputs
    contract['sequencer_variables']=[dict(id='payload_value',agent='control',width=8,default=37,fact_ids=['behavior'])]
    contract['sequences'][0]['controls']=[dict(operation=0,field='data',variable='payload_value')]
    if error=='cycle': contract['sequences'][0]['extends']='storage_access'
    elif error=='unknown_variable': contract['sequences'][0]['controls'][0]['variable']='unknown'
    elif error=='width': contract['sequencer_variables'][0]['width']=32
    else:
        contract['sequences'][0]['controls'][0]['field']='count'
        contract['sequencer_variables'][0]['width']=32
    with pytest.raises(ValueError):
        validate(CodePlan.model_validate(contract),spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']})


def test_dedicated_dependency_pass_drives_sequence_extension_and_controls(inputs):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    spec['sections'][0]['entries']*=2
    tasks=[dict(id=tid,title=tid,category='feature',goal='Storage access',interface_id='control',
                plan_pointers=[f'/sections/0/entries/{i}'],depends_on=[],queries=['storage control'])
           for i,tid in enumerate(('base_access','configured_access'))]
    original=workflow_model(contract).handlers['code_feature']
    def feature(payload):
        result=json.loads(json.dumps(original(payload)))
        if payload['task_id']=='configured_access':
            assert {d['mechanism'] for d in payload['dependency_handling']}=={'sequence_extension','p_sequencer_config'}
            result['sequences'][0].update(id='configured_sequence',extends='storage_access',
                controls=[dict(operation=0,field='data',variable='payload_value')])
            result['step_implementations'][0]['component_ids']=['configured_sequence']
            result['sequencer_variables']=[dict(id='payload_value',agent='control',width=8,default=42,fact_ids=['behavior'])]
        return result
    tests=json.loads(json.dumps(contract['tests']));tests[0]['stages']=[['configured_sequence']]
    llm=workflow_model(contract,
        code_grouping=lambda p:dict(understanding='Group one interface feature at a time',tasks=tasks,questions=[]),
        code_dependencies=lambda p:dict(understanding='Reuse base and parameterize shared sequencer',dependencies=[
            dict(task_id='configured_access',requires='base_access',reason='Reuse bringup actions',mechanism='sequence_extension'),
            dict(task_id='configured_access',requires='base_access',reason='Select legal payload',mechanism='p_sequencer_config',controls=['payload_value'])],questions=[]),
        code_feature=feature,
        code_collation=lambda p:dict(shared_setup=['Reuse reset'],execution_order=[['base_access'],['configured_access']],
            stimulus_approach=['Extend base'],check_approach=['Compare observations'],coverage_approach=['Monitor transfers'],questions=[]),
        code_integration=lambda p:dict(tests=tests,questions=[]))
    result=design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    assert result.sequences[-1].extends=='storage_access' and result.sequencer_variables[0].id=='payload_value'
    work=Path(json.loads((root/'output/code_work_manifest.json').read_text())['work_dir'])
    assert len(json.loads((work/'dependency_handling.json').read_text())['dependencies'])==2
    calls=[(n,p.get('task',{}).get('id') or p.get('task_id')) for n,p in llm.calls]
    assert calls.index(('code_feature','base_access')) < calls.index(('code_pseudocode','configured_access'))



def test_infrastructure_prompt_and_schema_do_not_require_functional_verification(inputs):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    llm=workflow_model(contract)
    original=llm._call
    seen=[]
    def call(name,instructions,payload,schema):
        if name in ('code_infrastructure','code_interface_base','code_interface'):
            assert 'Each test must observe at least one scoreboard comparison' not in instructions
            assert 'current infrastructure unit' in instructions
            if name=='code_infrastructure':
                assert 'actions' in schema['properties'] and 'stimulus_steps' not in schema['properties']
                assert 'check_steps' not in schema['properties'] and 'coverage_steps' not in schema['properties']
                seen.append(payload['profile'])
        return original(name,instructions,payload,schema)
    llm._call=call
    result=design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    assert result.clock=='tick' and {p['kind'] for p in seen}>={'protocol','collateral'}
    work=Path(json.loads((root/'output/code_work_manifest.json').read_text())['work_dir'])
    binding=json.loads((work/'common_binding.json').read_text())
    assert [s['id'] for s in binding['steps']]==['inventory','clock','reset','timing'] and binding['questions']==[]
    assert (work/'base_interfaces/control_if.sv').is_file()


def test_all_interface_bases_precede_collateral_and_utility_does_not_need_monitor(inputs):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    definition['ports'].append(dict(name='status_flag',direction='output',width=1))
    spec['sections'][0]['entries'][0]['text']+=' The status output is a utility observation.'
    spec['evidence_index']['CH-spec']['excerpt']+=' The status output is a utility observation.'
    llm=workflow_model(contract)
    inventory=llm.handlers['code_interfaces']
    def groups(payload):
        result=inventory(payload)
        result['interfaces'].append(dict(id='status_observation',title='Utility status',signals=['status_flag'],
                                         queries=['status output'],kind='utility'))
        return result
    llm.handlers['code_interfaces']=groups
    collateral=llm.handlers['code_interface']
    llm.handlers['code_interface']=lambda p:dict(facts=contract['facts']) if p['task_id']=='collateral_status_observation' else collateral(p)
    design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    names=[n for n,p in llm.calls]
    assert max(i for i,n in enumerate(names) if n=='code_interface_base')<names.index('code_interface')
    work=Path(json.loads((root/'output/code_work_manifest.json').read_text())['work_dir'])
    assert (work/'base_interfaces/status_observation_if.sv').is_file()
    utility=json.loads((work/'infrastructure_needs/status_observation.json').read_text())
    assert utility['level']=='scaffold_only'
    assert not (work/'collateral_status_observation.implementation.json').exists()
    assert not (work/'units/status_observation').exists()



def test_clock_and_reset_are_bound_without_any_model_call_from_small_fixed_steps(inputs):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    llm=workflow_model(contract)
    def forbidden(payload):
        assert payload['task']['id'] not in ('foundation_clock','foundation_reset'),'clock/reset must not reach the model'
        return normal(payload)
    normal=llm.handlers['code_infrastructure'];llm.handlers['code_infrastructure']=forbidden
    result=design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    assert (result.clock,result.reset,result.reset_active,result.clock_period_ns,result.reset_cycles)==('tick','clear','high',10,8)
    work=Path(json.loads((root/'output/code_work_manifest.json').read_text())['work_dir'])
    clock=json.loads((work/'foundation_clock.implementation.json').read_text())
    assert clock['clock']=='tick' and clock['facts'][0]['plan_pointer']=='/interfaces/groups/0/property_evidence/function'
    execution=json.loads((work/'execution_plan.json').read_text())
    assert [r['status'] for r in execution['steps'][:2]]==['PASS','PASS']


def test_interface_assessment_is_required_before_any_collateral(inputs):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    llm=workflow_model(contract)
    assessment=llm.handlers['code_interface_needs'];seen=[]
    def decide(payload):
        seen.append(payload)
        assert payload['base']['ports'] and payload['evidence']['source_excerpts']
        return assessment(payload)
    llm.handlers['code_interface_needs']=decide
    design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    names=[n for n,p in llm.calls]
    assert names.index('code_interface_base')<names.index('code_interface_needs')<names.index('code_interface')
    work=Path(json.loads((root/'output/code_work_manifest.json').read_text())['work_dir'])
    decision=json.loads((work/'infrastructure_needs/control.json').read_text())
    assert decision['level']=='full_agent' and decision['provenance']=='INFERRED_IMPLEMENTATION_CHOICE'
    execution=json.loads((work/'execution_plan.json').read_text())
    row=next(r for r in execution['steps'] if r['id']=='assessment_control')
    assert row['decision']['level']=='full_agent' and row['status']=='PASS'


def test_assessment_cannot_leave_inputs_unowned_or_build_unselected_agent(inputs):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    llm=workflow_model(contract,code_interface_needs=lambda p:dict(level='scaffold_only',reason='No work',
        responsibilities=['Ports only'],facts=contract['facts']))
    with pytest.raises(ValueError,match='explicit source-backed ownership'):
        design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    assert not any(n=='code_interface' for n,p in llm.calls)


def test_assessed_passive_output_interface_omits_active_and_coverage_components(inputs):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    definition['ports'].append(dict(name='status_flag',direction='output',width=1))
    spec['sections'][0]['entries'][0]['text']+=' The status output is a utility observation.'
    spec['evidence_index']['CH-spec']['excerpt']+=' The status output is a utility observation.'
    llm=workflow_model(contract);groups=llm.handlers['code_interfaces'];decide=llm.handlers['code_interface_needs'];build_unit=llm.handlers['code_interface']
    def inventory(p):
        result=groups(p);result['interfaces'].append(dict(id='status',title='Status',signals=['status_flag'],queries=['status output'],kind='utility'));return result
    llm.handlers['code_interfaces']=inventory
    llm.handlers['code_interface_needs']=lambda p:dict(level='passive_agent',reason='Observe status only',responsibilities=['Sample status'],coverage=False,facts=contract['facts']) if p['task_id']=='status' else decide(p)
    llm.handlers['code_interface']=lambda p:dict(agents=[dict(id='status',protocol='custom',bindings={'status':'status_flag'},active=False,coverage_enabled=False,fact_ids=['behavior'])],
        hooks=[dict(id='status_monitor',target='status',slot='monitor.body',purpose='Observe status',fact_ids=['behavior'])],facts=contract['facts']) if p['task_id']=='collateral_status' else build_unit(p)
    result=design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    ports=validate(result,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']})
    files,_=render(result,ports)
    assert 'uvm/status_monitor.svh' in files
    for component in ('driver','sequencer','coverage'):
        assert f'uvm/status_{component}.svh' not in files
    assert '_driver' not in files['uvm/status_agent.svh'] and '.cov' not in files['uvm/status_agent.svh']


def test_generated_components_must_match_assessed_minimum(inputs):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    llm=workflow_model(contract,code_interface_needs=lambda p:dict(level='full_agent',reason='Active bus needed',
        responsibilities=['Drive transfers'],coverage=False,facts=contract['facts']))
    with pytest.raises(ValueError,match='Coverage must match'):
        design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    work=Path(json.loads((root/'output/code_work_manifest.json').read_text())['work_dir'])
    assert (work/'base_interfaces/control_if.sv').exists()
    assert not (work/'units/control').exists()


def test_utility_configuration_builds_supported_tieoff_without_uvm_agent(inputs):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    text='The utility enable input is held at zero during normal operation.'
    definition['ports'].append(dict(name='enable_static',direction='input',width=1))
    spec['sections'][0]['entries'][0]['text']+=' '+text
    spec['evidence_index']['CH-spec']['excerpt']+=' '+text
    contract['facts'].append(dict(id='enable_idle',statement=text,quote=text,source_id='CH-spec',plan_pointer='/sections/0/entries/0'))
    llm=workflow_model(contract);groups=llm.handlers['code_interfaces'];decide=llm.handlers['code_interface_needs'];collateral=llm.handlers['code_interface']
    def inventory(p):
        result=groups(p);result['interfaces'].append(dict(id='enable_config',title='Utility enable',signals=['enable_static'],queries=['utility enable input'],kind='utility'));return result
    llm.handlers['code_interfaces']=inventory
    llm.handlers['code_interface_needs']=lambda p:dict(level='utility_config',reason='Fixed documented input',responsibilities=['Apply supported idle value'],facts=contract['facts']) if p['task_id']=='enable_config' else decide(p)
    llm.handlers['code_interface']=lambda p:dict(tie_offs=[dict(id='enable_tie',signal='enable_static',value=0,fact_ids=['enable_idle'])],facts=contract['facts']) if p['task_id']=='collateral_enable_config' else collateral(p)
    result=design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    assert len(result.agents)==1 and result.tie_offs[0].signal=='enable_static'
    assert not any(a.id=='enable_config' for a in result.agents)



def test_undocumented_reset_polarity_waits_for_human_instead_of_failing(inputs):
    from dv_agent.quality.human_review import HumanReviewPending
    root,spec,definition,contract,rtl=inputs
    spec['interfaces']['groups'][1]['signals'][0].update(active_level='unknown',active_level_documented=False)
    (root/'plan.json').write_text(json.dumps(spec))
    llm=workflow_model(contract)
    with pytest.raises(HumanReviewPending):
        build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[rtl])
    state=json.loads((root/'output/code_generation_state.json').read_text())
    assert state['status']=='WAITING_HUMAN'
    assert json.loads((root/'output/code_work_manifest.json').read_text())['status']=='WAITING_HUMAN'
    assert not any(n=='code_interfaces' for n,p in llm.calls)
    request=json.loads(next((root/'output/human_review').glob('*/request.json')).read_text())
    assert request['unit']=='foundation_reset' and request['allowed_fields']==['reset','reset_active','reset_cycles']
    assert 'asserted high (1) or low (0)' in request['blockers'][0]



def test_human_approval_revises_plan_then_resumes_and_is_never_asked_again(inputs):
    from dv_agent.quality.human_review import approve,review_handler
    root,spec,definition,contract,rtl=inputs
    spec['sections'][0].update(generator='entries',heading='Checks',status='PASS')
    spec['sections'][0]['entries'][0].update(kind='check',id='storage_check',validation=[],cited_req_ids=[])
    spec['interfaces']['groups'][1]['signals'][0].update(active_level='unknown',active_level_documented=False)
    (root/'plan.json').write_text(json.dumps(spec))
    llm=workflow_model(contract)
    approvals=[]
    def human(folder,request):
        approvals.append(request['id'])
        approve(folder,request['id'],request['nonce'],{'reset_active':'high'},'Design engineer confirmed',
                actor='designer',channel='terminal',reference='tty:confirmed')
    with review_handler(human):
        result=build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[rtl])
    assert any(s.startswith('HUMAN-') for s in json.loads((root/'plan.json').read_text())['evidence_index'])
    assert result['contract']=='verification_codegen_v1' and len(approvals)==1  # one question, one answer, no loop
    plan=json.loads((root/'plan.json').read_text())
    assert plan['human_approvals'][0]['bindings']=={'reset_active':'high'}
    assert 'Approved by user designer' in (root/'plan.md').read_text()
    assert 'Approved by user designer' in (root/'plan.html').read_text()
    reset=json.loads(next((root/'output/code_work').glob('*/foundation_reset.implementation.json')).read_text())
    assert reset['reset_active']=='high' and reset['facts'][-1]['source_id'].startswith('HUMAN-')


def test_invalid_fact_ids_are_normalized_everywhere_and_references_follow():
    from dv_agent.codegen.contracts import IDENTIFIER_RULE, identifier, normalize_fact_ids, safe_identifier
    answer={'facts':[{'id':'F-RST-01'},{'id':'F_RST_01'},{'id':'f.2 x'},{'id':'ok1'}],
            'sequences':[{'fact_ids':['F-RST-01','ok1','f.2 x']}],
            'nested':{'agents':[{'fact_ids':['F-RST-01'],'facts':[{'id':'1st'}]}]}}
    renamed=normalize_fact_ids(answer)
    assert renamed=={'F-RST-01':'F_RST_01_2','f.2 x':'f_2_x','1st':'f_1st'}  # a collision gets a suffix, never a duplicate
    assert [f['id'] for f in answer['facts']]==['F_RST_01_2','F_RST_01','f_2_x','ok1']
    assert answer['sequences'][0]['fact_ids']==['F_RST_01_2','ok1','f_2_x'] and answer['nested']['agents'][0]['fact_ids']==['F_RST_01_2']
    assert all(identifier(f['id']) for f in answer['facts'])
    assert normalize_fact_ids(answer)=={}  # valid ids are left alone
    assert safe_identifier('class')=='class_id' and safe_identifier('--')=='id' and safe_identifier('9')=='f_9'
    with pytest.raises(ValueError,match='letters, digits and underscores'): identifier('F-RST-01')
    assert 'hyphens' in IDENTIFIER_RULE


def test_validate_facts_lists_every_bad_identifier_with_the_rule(inputs):
    from dv_agent.codegen.contracts import Fact
    from dv_agent.codegen.validate import validate_facts
    facts=[Fact(id=i,statement='s',source_id='CH-1',quote='quote text',plan_pointer='/sections/0') for i in ('A-1','b','C-3')]
    with pytest.raises(ValueError) as caught: validate_facts(facts,{},{})
    assert "['A-1', 'C-3']" in str(caught.value) and 'underscores' in str(caught.value)



def test_hyphenated_fact_ids_need_no_repair_call_and_the_rename_is_recorded(inputs):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    llm=workflow_model(contract);normal=llm.handlers['code_pseudocode'];seen=[]
    def answer(payload):
        result=normal(payload)
        seen.append(payload)
        for number,fact in enumerate(result['facts'],1): fact['id']=f'F-IF-{number:02d}'
        return result
    llm.handlers['code_pseudocode']=answer
    design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')
    assert len(seen)==1 and 'repair_feedback' not in seen[0]  # one call: the ids were normalized, not refused
    context=json.loads((root/'output/code_context.json').read_text())
    renamed=[r['renamed_fact_ids'] for r in context['requests'] if r.get('renamed_fact_ids')]
    assert renamed and all(new.startswith('F_IF_') for m in renamed for new in m.values())


def test_a_refused_answer_returns_with_the_rule_and_its_own_previous_output(inputs):
    from dv_agent.codegen.contracts import IDENTIFIER_RULE
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    llm=workflow_model(contract);normal=llm.handlers['code_collation'];calls=[]
    def collate(payload):
        calls.append(payload)
        result=normal(payload)
        if len(calls)==1: result['check_approach']=[]
        else:
            assert payload['repair_rules']=={'identifiers':IDENTIFIER_RULE}
            assert payload['previous_output']['check_approach']==[] and 'nonempty check_approach' in payload['repair_feedback']
        return result
    llm.handlers['code_collation']=collate
    design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output',pseudocode_only=True)
    assert len(calls)==2


def test_prompts_state_the_identifier_format_and_how_to_use_repair_feedback():
    from dv_agent.codegen.reasoning import INSTRUCTIONS
    from dv_agent.codegen.units import INFRASTRUCTURE_INSTRUCTIONS
    for text in (INSTRUCTIONS,INFRASTRUCTURE_INSTRUCTIONS):
        assert 'never hyphens' in text and 'repair_feedback' in text and 'previous_output' in text


def test_generated_testbench_instantiates_the_common_environment_and_compiles_it_first(inputs):
    result=build(inputs)
    code=Path(result['code_dir'])
    for name in ('common_cfg.svh','common_agent.svh','common_env.svh','common_pkg.sv'):
        assert (code/'common_uvc/common'/name).is_file()
    test=(code/'tests/basic_functional.svh').read_text()
    assert 'cg_env::type_id::create("cmn_env",this)' in test and 'cmn_cfg.bind_reset(' in test
    assert 'clock_agent::type_id::create' not in test and 'reset_agent::type_id::create' not in test  # the common agent owns them
    assert 'cmn_env.cmn_agent.apply_reset();' in test and 'reset_pulse_seq::type_id::create' not in test
    files=(code/'compile.f').read_text().split()
    assert files.index('common_uvc/reset/reset_pkg.sv')<files.index('common_uvc/common/common_pkg.sv')<files.index(next(f for f in files if f.endswith('verification_top.sv')))
    assert 'import common_pkg::*;' in (code/'peripheral_verification_pkg.sv').read_text()
    env=(code/'common_uvc/common/common_env.svh').read_text()
    assert 'class common_env extends uvm_env' in env and 'common_agent::type_id::create' in env
    generated_env=(code/'uvm/cg_env.svh').read_text()
    assert 'class cg_env extends common_env' in generated_env
    assert 'super.build_phase(phase)' in generated_env and 'super.connect_phase(phase)' in generated_env
    assert 'common_agent cmn_agent;' in env and 'create("cmn_agent", this)' in env
    assert 'common_env common_infra' not in test
    agent=(code/'common_uvc/common/common_agent.svh').read_text()
    assert 'clock_agent::type_id::create("clk_agent"' in agent and 'reset_agent::type_id::create("rst_agent"' in agent
