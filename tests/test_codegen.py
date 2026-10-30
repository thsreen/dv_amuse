"""Reusable infrastructure tests: renamed DUT, typed bindings, evidence and real template artifacts."""
import json
from pathlib import Path

import pytest

from dv_agent.codegen import build_project
from dv_agent.codegen.contracts import CodePlan
from dv_agent.codegen.render import render
from dv_agent.codegen.validate import validate
from dv_agent.llm import FakeLLM


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
    llm=FakeLLM({'code_design':lambda payload: CodePlan.model_validate(contract).model_dump(),
                 'code_review':lambda payload: {'problems':[]}})
    for _ in range(2):
        build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[rtl],compile=False)
    assert [name for name,_ in llm.calls]==['code_design','code_review']
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
        assert '-I' in cmd and '+UVM_TESTNAME=basic_functional' in cmd
        sites=[]
        for check in manifest['assertion_covers']:
            sites += [dict(file=check['file'],line=check['assertion_line'],kind='assert',**{'pass':1,'fail':0}),
                      dict(file=check['file'],line=check['cover_line'],kind='cover',**{'pass':1,'fail':0}),
                      dict(file=check['file'],line=check['activation_line'],kind='cover',**{'pass':1,'fail':0})]
        Path(kwargs['env']['XEZIM_COV_DB']).write_text(json.dumps(dict(assertions=sites,covergroups=[dict(name='transactions',samples=2)])))
        log='FUNCTIONAL_TEST_PASS basic_functional\nUVM_ERROR : 0\nUVM_FATAL : 0\n'
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
        invalid=json.loads(json.dumps(contract))
        invalid['sequences'][0]['operations'][0]['data']=256
        return CodePlan.model_validate(contract if payload.get('repair') else invalid).model_dump()
    llm=FakeLLM({'code_design':answer,'code_review':lambda payload: {'problems':[]}})
    result=build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[rtl],compile=False)
    assert result['tests'] and len(calls)==2
    assert 'exceeds' in calls[1]['repair']['validation_feedback']
    assert (root/'output/contract_repair.json').is_file()


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
    from dv_agent.llm import LLMError
    root,_,_,_,rtl=inputs
    def fail(payload): raise LLMError('transient','provider detail must not be persisted')
    llm=FakeLLM({'code_design':fail})
    with pytest.raises(ValueError,match='retry /code'):
        build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[rtl],compile=False)
    report=(root/'output/code_questions.json').read_text()
    assert 'transient' in report and 'provider detail' not in report
