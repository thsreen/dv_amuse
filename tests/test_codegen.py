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
    names={'addr':'index','wdata':'push','rdata':'pull','sel':'lanes','we':'writing','stb':'request','cyc':'cycle','ack':'ready'}
    directions={r:'output' if r in ('rdata','ack') else 'input' for r in names}
    ports=[dict(name='tick',direction='input',width=1),dict(name='clear',direction='input',width=1)]
    ports += [dict(name=n,direction=directions[r],width=3 if r=='addr' else 8 if r in ('wdata','rdata') else 1) for r,n in names.items()]
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
    handlers.update(overrides)
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
    assert [name for name,_ in llm.calls]==['code_grouping','code_pseudocode','code_collation','code_foundation','code_feature','code_integration','code_review']
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
                           contract_path=root/'contract.json',rtl_files=[rtl])
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
    assert max(i for i,n in enumerate(names) if n=='code_pseudocode') < names.index('code_collation') < names.index('code_feature')
    for name,payload in llm.calls:
        if name=='code_feature': assert 'collated_approach' in payload and 'pseudocode' in payload
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
        return dict(understanding='Grouped storage features',tasks=[dict(id=f'b{batch}_t{i//6}',title='Storage group',
            category='feature',goal='Storage access',plan_pointers=[e['plan_pointer'] for e in items[i:i+6]],
            depends_on=[],queries=['storage clock reset bus']) for i in range(0,len(items),6)],questions=[])
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
    assert [n for n,p in llm.calls]==['code_grouping','code_pseudocode','code_collation']
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
    assert (Path(manifest['work_dir'])/'COLLATED_PSEUDOCODE.md').is_file()


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
                           contract_path=tmp_path/'code_contract.json',rtl_files=list((repo/'rtl/verilog').glob('*.v')))
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
    assert starts == ['code_grouping', 'code_pseudocode:storage_feature', 'code_collation',
                      'code_foundation', 'code_feature:storage_feature', 'code_integration',
                      'code_validation', 'code_review', 'code_hooks', 'code_render',
                      'code_compile', 'code_publish']
    configured = next(e['steps'] for e in events if e['kind']=='substeps_configured')
    assert any(s['label']=='Understand Storage access' for s in configured)
    assert any(e.get('id')=='code_compile' and e.get('status')=='NOT_RUN' for e in events)
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
