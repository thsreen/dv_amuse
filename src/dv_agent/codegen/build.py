"""Checkpointed implementation pipeline; publishes a manifest only after complete rendering."""
import json
from contextlib import contextmanager
from pathlib import Path

from ..core.fsutil import atomic_write_text
from ..graph.graph import load_graph
from ..core.llm import LLMError
from ..core.progress import emit
from .contracts import CodePlan, digest
from .reasoning import design, eligible_items, implement, review
from .render import render, template_hash
from .simulator import compile_project
from .validate import validate
from .events import stage, skip, STEPS


@contextmanager
def project_lock(directory):
    # OS-managed lock releases even on process death; no stale lock files to delete.
    import fcntl
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/'.codegen.lock').open('a') as handle:
        try: fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Code generation already running in this output directory') from None
        try: yield
        finally: fcntl.flock(handle,fcntl.LOCK_UN)


def load_sources(plan, graph_path=None):
    sources={cid:info.get('excerpt','') for cid,info in plan.get('evidence_index',{}).items()}
    if graph_path and Path(graph_path).is_file():
        graph=load_graph(Path(graph_path))
        for cid,node in graph.nodes(data=True):
            if node.get('type') in ('chunk','requirement'):
                sources[cid]=node.get('quote') or node.get('text','')
    def walk(value):
        if isinstance(value,dict):
            if value.get('chunk_id') and value.get('quote'):
                sources.setdefault(value['chunk_id'],value['quote'])
            for child in value.values(): walk(child)
        elif isinstance(value,list):
            for child in value: walk(child)
    walk(plan)
    return sources


def build_project(plan_path, interface_path, directory, *, llm=None, contract_path=None,
                  rtl_files=(), expected_top=None, compile=True):
    plan_path,interface_path,directory=Path(plan_path).resolve(),Path(interface_path).resolve(),Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    with project_lock(directory):
        atomic_write_text(directory/'code_generation_state.json',json.dumps(dict(status='BUILDING'))+'\n')
        try:
            result=_build(plan_path,interface_path,directory,llm=llm,contract_path=contract_path,
                          rtl_files=rtl_files,expected_top=expected_top,compile=compile)
            status='BUILT_NEEDS_REVIEW' if result['compile']['status'] in ('PASS','NOT_RUN') else 'BLOCKED'
            atomic_write_text(directory/'code_generation_state.json',json.dumps(dict(status=status,build_id=result['build_id']))+'\n')
            return result
        except (Exception, KeyboardInterrupt) as exc:
            # No credentials/provider exception bodies in the persistent issue artifact.
            reason=str(exc) if isinstance(exc,ValueError) else 'Model call failed: '+exc.kind if isinstance(exc,LLMError) else type(exc).__name__
            atomic_write_text(directory/'code_questions.json',json.dumps(dict(status='BLOCKED',questions=[reason]),indent=2)+'\n')
            atomic_write_text(directory/'code_generation_state.json',json.dumps(dict(status='BLOCKED',reason=reason))+'\n')
            if isinstance(exc,LLMError): raise ValueError(reason+'; retry /code to reuse successful checkpoints') from None
            raise


def _build(plan_path,interface_path,directory,*,llm,contract_path,rtl_files,expected_top,compile,compiler_feedback=None):
    specification=json.loads(plan_path.read_text())
    if specification.get('source_authority')=='RTL_INFERRED':
        raise ValueError('RTL-derived specification requires RTL engineer validation before functional code generation')
    definition=json.loads(interface_path.read_text())
    sources=load_sources(specification,plan_path.parent/'graph.json')
    emit('code [1/5]: analyze documented source evidence and design implementation contract')
    if contract_path:
        skip(*(sid for sid,label in STEPS[1:8]))
        plan=CodePlan.model_validate(json.loads(Path(contract_path).read_text()))
    elif llm:
        plan=design(llm,specification,definition,sources,directory)
    else:
        raise ValueError('Functional generation requires an explicit code contract or an enabled model')
    if expected_top and plan.top!=expected_top:
        raise ValueError('Code contract top does not match the selected design')
    emit('code [2/5]: validate evidence, ownership, protocol bindings and comparisons')
    # One semantic repair after deterministic/reviewer feedback. API transport retries
    # remain in the shared client; explicit operator contracts are never rewritten.
    for attempt in range(2):
        try:
            with stage('code_validation'):
                ports=validate(plan,specification,definition,sources)
            if llm:
                with stage('code_review'): review(llm,plan,directory)
            else: skip('code_review')
            break
        except ValueError as exc:
            if contract_path or not llm or attempt==1: raise
            atomic_write_text(directory/'contract_repair.json',json.dumps(
                dict(attempt=1,feedback=str(exc),previous_contract=plan.model_dump()),indent=2)+'\n')
            plan=design(llm,specification,definition,sources,directory,previous=plan.model_dump(),feedback=str(exc))
            if expected_top and plan.top!=expected_top:
                raise ValueError('Repaired code contract top does not match the selected design')
    if not plan.tests:
        atomic_write_text(directory/'code_plan.json',plan.model_dump_json(indent=2)+'\n')
        raise ValueError('No executable tests: '+'; '.join(plan.questions or ['Implementation contract is incomplete']))
    if not plan.routes and not any(r.access!='WO' for r in plan.registers):
        raise ValueError('Functional tests require an enabled predictor/scoreboard comparison')
    if not llm and not contract_path: raise ValueError('Unreviewable implementation contract')
    atomic_write_text(directory/'code_plan.json',plan.model_dump_json(indent=2)+'\n')
    emit('code [3/5]: implement declared behavior hooks and render reusable templates')
    if plan.hooks and not llm:
        raise ValueError('Custom protocol hooks require model implementation and validation')
    with stage('code_hooks') as outcome:
        hook_code=implement(llm,plan,directory,compiler_feedback=compiler_feedback) if llm else {}
        if not plan.hooks: outcome['status']='NOT_RUN'
    for agent in plan.agents:
        if agent.protocol=='custom':
            slots={h.slot for h in plan.hooks if h.target==agent.id and hook_code.get(h.id)}
            if not {'driver.body','monitor.body'} <= slots:
                raise ValueError('Custom protocol requires implemented driver and monitor hooks')
    with stage('code_render'):
        artifacts,compile_files=render(plan,ports,hook_code)
    rtl=[Path(p).resolve() for p in rtl_files]
    if not rtl or any(not p.is_file() for p in rtl):
        raise ValueError('Explicit RTL files are required for compilation (not model inference)')
    if plan_path in rtl or interface_path in rtl:
        raise ValueError('RTL file list contains a collateral input')
    hashes={str(p):digest(p.read_text(errors='replace')) for p in rtl}
    fingerprint=digest([plan.model_dump(),definition,template_hash(),hook_code,hashes,
                        {name:digest(text) for name,text in artifacts.items()}])
    code=directory/'code'/fingerprint[:16]
    reused=code.is_dir() and (code/'tests.json').is_file()
    code.mkdir(parents=True,exist_ok=True)
    for name,text in artifacts.items():
        target=code/name
        if not target.resolve().is_relative_to(code): raise ValueError('Template output escapes project directory')
        if target.exists() and target.read_text()!=text:
            raise ValueError(f'Generated file edited; preserve extension files instead: {target.name}')
        if not target.exists(): atomic_write_text(target,text)
    manifest=dict(contract=plan.contract,status='BUILT_NEEDS_REVIEW',build_id=fingerprint,code_dir=str(code),
                  source_plan=str(plan_path),interface=str(interface_path),template_hash=template_hash(),
                  input_hashes={str(path):digest(path.read_text()) for path in (plan_path,interface_path)},
                  rtl_files=[str(p) for p in rtl],rtl_hashes=hashes,top=plan.top,compile_files=compile_files,
                  defines=plan.defines,
                  files={name:digest(text) for name,text in artifacts.items()},
                  coverage_collectors=[dict(id=a.id+'_coverage',source='monitor '+a.id,
                                            file=f'uvm/{a.id}_coverage.svh',sampling='completed observed transaction',
                                            fact_ids=a.fact_ids) for a in plan.agents]
                                      + [dict(id=c.id,source='monitor '+c.agent,file=f'uvm/{c.id}_coverage.svh',
                                              sampling='completed observed transaction',fact_ids=c.fact_ids) for c in plan.coverage]
                                      + ([dict(id='system_coverage',source='all interface monitors',
                                               file='uvm/cg_system_coverage.svh',sampling='observed route event',
                                               fact_ids=sorted({f for r in plan.routes for f in r.fact_ids}))] if plan.routes else []),
                  tests=[dict(name=t.id,kind='uvm_functional',top='verification_top',seed=t.seed,
                              minimum_comparisons=t.minimum_comparisons) for t in plan.tests],
                  policy=dict(source='documented expected behavior; template-owned infrastructure',
                              guidance='Plan proposals guide implementation but are not expectation authority',
                              kept=len(plan.facts),skipped=max(0,len(eligible_items(specification,sources))-len({f.plan_pointer for f in plan.facts}))),
                  assertion_covers=[dict(check_id=c.id,assertion='a_'+c.id,cover='c_'+c.id,activation_cover='activation_'+c.id,
                      file=f'checks/{c.agent}_assertions.sv',
                      assertion_line=next(i for i,line in enumerate(artifacts[f'checks/{c.agent}_assertions.sv'].splitlines(),1) if f'a_{c.id}:' in line),
                      cover_line=next(i for i,line in enumerate(artifacts[f'checks/{c.agent}_assertions.sv'].splitlines(),1) if f'c_{c.id}:' in line),
                      activation_line=next(i for i,line in enumerate(artifacts[f'checks/{c.agent}_assertions.sv'].splitlines(),1) if f'activation_{c.id}:' in line)) for c in plan.checks],
                  uvm_status='NEEDS_REVIEW',expected_behavior_review='NEEDS_REVIEW',
                  operational_limits=dict(request_timeout_cycles=plan.request_timeout_cycles,
                                          note='testbench operational limits are not DUT timing requirements'))
    if llm and not contract_path:
        manifest['work_documents']=str(directory/'code_work_manifest.json')
    items=[]
    for category in ('agents','registers','sequences','routes','checks','tests','hooks','coverage'):
        for item in getattr(plan,category):
            items.append(dict(id=item.id,kind=category,fact_ids=item.fact_ids,
                              plan_references=[next(f for f in plan.facts if f.id==fid).plan_pointer for fid in item.fact_ids],
                              code_files=[name for name,text in artifacts.items() if item.id in text]))
    for path,value in (('code_plan.json',plan.model_dump()),('traceability.json',dict(items=items)),
                       ('code_questions.json',dict(status='NEEDS_REVIEW' if plan.questions else 'PASS',questions=plan.questions))):
        atomic_write_text(code/path,json.dumps(value,indent=2)+'\n')
    emit('code [4/5]: compile generated UVM and preserve diagnostics')
    with stage('code_compile') as outcome:
        manifest['compile']=compile_project(manifest) if compile else dict(status='NOT_RUN',reason='compile disabled explicitly')
        outcome['status']=manifest['compile']['status']
    if llm and plan.hooks and compiler_feedback is None and manifest['compile']['status']=='FAIL':
        # Repair only diagnostics naming a generated extension file. Framework,
        # missing-library and DUT errors cannot authorize model edits to those files.
        diagnostics=Path(manifest['compile']['log']).read_text(errors='replace').splitlines()
        feedback={}
        for hook in plan.hooks:
            filename=('cg_scoreboard.svh' if hook.slot=='scoreboard.compare' else
                      hook.target+'_'+{'driver.body':'driver','monitor.body':'monitor','coverage.sample':'coverage'}[hook.slot]+'.svh')
            lines=[line for line in diagnostics if filename in line]
            if lines: feedback[hook.id]={'previous_code':hook_code[hook.id],'compiler_diagnostics':'\n'.join(lines)[:8000]}
        if feedback:
            atomic_write_text(code/'failed_compile_manifest.json',json.dumps(manifest,indent=2)+'\n')
            atomic_write_text(directory/'compiler_repair.json',json.dumps(dict(attempt=1,feedback=feedback),indent=2)+'\n')
            return _build(plan_path,interface_path,directory,llm=llm,contract_path=contract_path,rtl_files=rtl_files,
                          expected_top=expected_top,compile=compile,compiler_feedback=feedback)
    manifest['reused']=reused
    emit('code [5/5]: publish code manifest, source lineage and test inventory')
    with stage('code_publish'):
        atomic_write_text(code/'tests.json',json.dumps(manifest,indent=2)+'\n')
        atomic_write_text(directory/'code_manifest.json',json.dumps(manifest,indent=2)+'\n')
        atomic_write_text(directory/'traceability.json',json.dumps(dict(items=items),indent=2)+'\n')
        questions=list(plan.questions)
        compile_status=manifest['compile']['status']
        if compile_status not in ('PASS','NOT_RUN'):
            questions.append('Compilation '+compile_status+': '+manifest['compile'].get('reason',manifest['compile'].get('log','see compile_result.json')))
        question_status='BLOCKED' if compile_status not in ('PASS','NOT_RUN') else 'NEEDS_REVIEW' if questions else 'PASS'
        for target in (directory/'code_questions.json',code/'code_questions.json'):
            atomic_write_text(target,json.dumps(dict(status=question_status,questions=questions),indent=2)+'\n')
    return manifest
