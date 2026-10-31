"""Isolated Xezim adapter: capability discovery, compilation, logs and coverage evidence."""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from ..core.fsutil import atomic_write_text
from .contracts import digest


def run_saved_project(directory, *, regress=False, timeout=180):
    directory=Path(directory)
    state=directory/'code_generation_state.json'
    if state.is_file() and json.loads(state.read_text()).get('status') in ('BLOCKED','BUILDING','WAITING_HUMAN'):
        return dict(status='BLOCKED',reason='Latest code generation is incomplete; rebuild before execution',tests=[])
    path=directory/'code_manifest.json'
    if not path.is_file(): raise ValueError('No code manifest; run /code or build-code first')
    manifest=json.loads(path.read_text())
    if manifest.get('contract')!='verification_codegen_v1':
        raise ValueError('run-code requires a functional verification manifest; use orchestrator /run for legacy smoke')
    return run_project(manifest,regress=regress,timeout=timeout)


def discover():
    binary=os.getenv('XEZIM_BIN') or shutil.which('xezim')
    if not binary:
        local=Path(__file__).resolve().parents[3]/'.e2e-bin'/'xezim'
        if local.is_file(): binary=str(local)
    if not binary or not Path(binary).is_file():
        return dict(status='BLOCKED',reason='Xezim not found; set XEZIM_BIN')
    version=subprocess.run([str(binary),'-V'],capture_output=True,text=True,timeout=10)
    help_result=subprocess.run([str(binary),'--help'],capture_output=True,text=True,timeout=10)
    help_text=help_result.stdout+help_result.stderr
    root=Path(os.environ['XEZIM_UVM_DIR']) if os.getenv('XEZIM_UVM_DIR') else None
    library=None
    if root:
        for candidate in (root/'uvm_pkg.sv',root/'src'/'uvm_pkg.sv'):
            if candidate.is_file() and (candidate.parent/'uvm_macros.svh').is_file():
                library=candidate.resolve(); break
    if '--compile' not in help_text or '--simulate' not in help_text:
        return dict(status='BLOCKED',reason='Simulator lacks required compile/simulate options',binary=str(binary))
    return dict(status='PASS' if library else 'BLOCKED',reason='' if library else 'Set XEZIM_UVM_DIR to a UVM source release',
                binary=str(Path(binary).resolve()),version=version.stdout.strip(),
                uvm=str(library) if library else None, error_exit='--error-exit' in help_text,
                code_coverage='--code-coverage' in help_text)


def command(manifest, capabilities, *, simulate=False, test=None):
    code=Path(manifest['code_dir']).resolve()
    rtl=[str(Path(p).resolve()) for p in manifest['rtl_files']]
    library=Path(capabilities['uvm'])
    directories={code,code/'common_uvc'/'clock',code/'common_uvc'/'reset',code/'common_uvc'/'common',library.parent}
    directories.update(Path(p).parent for p in rtl)
    cmd=[capabilities['binary'],'--simulate' if simulate else '--compile','-s','verification_top']
    for directory in sorted(directories): cmd+=['-I',str(directory)]
    cmd+=['-D','UVM_NO_DPI','-D','UVM_REPORT_DISABLE_FILE_LINE']
    for define in manifest.get('defines',[]): cmd+=['-D',define]
    if capabilities.get('error_exit'): cmd+=['--error-exit']
    cmd+=[str(library)]+rtl+[str(code/p) for p in manifest['compile_files']]
    if test:
        cmd += ['+UVM_TESTNAME='+test.get('uvm_testname',test['name']), '+seed='+str(test['seed'])]
        if 'clock_period_ps' in test: cmd+=['+CLOCK_PERIOD_PS='+str(test['clock_period_ps'])]
    return cmd


def compile_project(manifest, timeout=180):
    code=Path(manifest['code_dir'])
    for source,expected in manifest.get('input_hashes',{}).items():
        if not Path(source).is_file() or digest(Path(source).read_text())!=expected:
            return dict(status='BLOCKED',reason='Testplan/interface changed; regenerate before execution')
    for source,expected in manifest.get('rtl_hashes',{}).items():
        if not Path(source).is_file() or digest(Path(source).read_text(errors='replace'))!=expected:
            return dict(status='BLOCKED',reason='RTL sources changed; regenerate before execution')
    for name,expected in manifest.get('files',{}).items():
        if not (code/name).is_file() or digest((code/name).read_text())!=expected:
            return dict(status='BLOCKED',reason='Generated source changed; rebuild and review before execution')
    report=discover()
    if report['status']!='PASS':
        atomic_write_text(code/'compile_result.json',json.dumps(report,indent=2)+'\n')
        return report
    fingerprint=manifest['build_id']+report['version']+report['uvm']
    result_file=code/'compile_result.json'
    if result_file.is_file():
        previous=json.loads(result_file.read_text())
        if previous.get('status')=='PASS' and previous.get('fingerprint')==fingerprint:
            return previous | {'reused':True}
    try:
        result=subprocess.run(command(manifest,report),cwd=code,text=True,stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,timeout=timeout,check=False)
        log=result.stdout
        status='PASS' if result.returncode==0 else 'FAIL'
    except subprocess.TimeoutExpired as exc:
        log=exc.stdout or ''; log=log.decode(errors='replace') if isinstance(log,bytes) else log
        status='TIMEOUT'
    atomic_write_text(code/'compile.log',log)
    report.update(status=status,log=str(code/'compile.log'),fingerprint=fingerprint)
    atomic_write_text(result_file,json.dumps(report,indent=2)+'\n')
    return report


def run_project(manifest, *, regress=False, timeout=180):
    compile_result=compile_project(manifest,timeout)
    if compile_result['status']!='PASS':
        return dict(status='BLOCKED',reason='Functional compilation unavailable or failed',compile=compile_result,tests=[])
    results=[]
    code=Path(manifest['code_dir'])
    for test in manifest['tests'] if regress else manifest['tests'][:1]:
        directory=code/'simulation'/test['name']/str(test['seed'])/str(time.time_ns())
        directory.mkdir(parents=True,exist_ok=True)
        env=dict(os.environ,XEZIM_COV_DB=str(directory/'coverage.json'))
        comparisons=[]
        observed_periods=[]
        uvm_counts={}
        try:
            completed=subprocess.run(command(manifest,compile_result,simulate=True,test=test),cwd=directory,env=env,
                                     text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout,check=False)
            log=completed.stdout
            marker='FUNCTIONAL_TEST_PASS '+test.get('uvm_testname',test['name'])
            errors=bool(re.search(r'UVM_(?:ERROR|FATAL)\s+(?!: *0\b)|\b(?:CLOCK_PERIOD_MISMATCH|DATA_MISMATCH|REGISTER_MISMATCH|UNDRAINED|NO_COMPARISON|MON_X)\b',log))
            status='PASS' if completed.returncode==0 and marker in log and not errors else 'FAIL'
            reason=(f'Xezim exit {completed.returncode}' if completed.returncode else
                    'UVM or scoreboard/monitor errors reported' if errors else
                    'Functional completion marker missing' if marker not in log else 'Functional checks completed')
            comparisons=[int(n) for n in re.findall(r'\[SCOREBOARD_SUMMARY\]\s+comparisons=(\d+)',log)]
            uvm_counts={kind:int(count) for kind,count in re.findall(r'^UVM_(INFO|WARNING|ERROR|FATAL)\s*:\s*(\d+)',log,re.M)}
            if status=='PASS' and not manifest.get('demo') and (not comparisons or sum(comparisons)<test['minimum_comparisons']):
                status,reason='BLOCKED','Scoreboard comparison evidence missing or below required minimum'
            observed_periods=[int(n) for n in re.findall(r'CLOCK_PERIOD_OBSERVED_PS\s+(\d+)',log)]
            if status=='PASS' and 'clock_period_ps' in test:
                if not observed_periods:
                    status,reason='BLOCKED','Monitor-confirmed clock period evidence is missing'
                elif any(n!=test['clock_period_ps'] for n in observed_periods):
                    status,reason='FAIL','Observed clock period differs from the selected campaign setting'
        except subprocess.TimeoutExpired as exc:
            log=exc.stdout or ''; log=log.decode(errors='replace') if isinstance(log,bytes) else log
            status,reason='TIMEOUT','Simulation deadline exceeded'
        atomic_write_text(directory/'simulation.log',log)
        coverage=dict(status='NOT_RUN',reason='No coverage artifact produced')
        if (directory/'coverage.json').is_file():
            try:
                raw=json.loads((directory/'coverage.json').read_text())
                coverage=dict(status='RECORDED',path=str(directory/'coverage.json'),data=raw)
            except json.JSONDecodeError:
                coverage=dict(status='FAIL',reason='Invalid coverage JSON')
        assertion_results=[]
        for check in manifest.get('assertion_covers',[]):
            sites=coverage.get('data',{}).get('assertions',[])
            def site(line):
                return next((s for s in sites if Path(s.get('file','')).name==Path(check['file']).name and s.get('line')==line),None)
            actual,activation,covered=site(check['assertion_line']),site(check['activation_line']),site(check['cover_line'])
            state=('NOT_RUN' if actual is None or activation is None or covered is None else
                   'FAIL' if actual.get('fail',0)>0 or activation.get('pass',0)==0 or covered.get('pass',0)==0 else 'PASS')
            assertion_results.append(dict(check_id=check['check_id'],status=state,activation_hits=(activation or {}).get('pass',0),
                                          property_hits=(covered or {}).get('pass',0)))
        if assertion_results and any(r['status']!='PASS' for r in assertion_results):
            if any(r['status']=='FAIL' for r in assertion_results):
                status,reason='FAIL','Assertion activation/property coverage failed'
            elif status=='PASS':
                status,reason='BLOCKED','Assertion activation/coverage evidence incomplete'
        if status=='PASS' and not manifest.get('demo') and (coverage.get('status')!='RECORDED' or not any(
                group.get('samples',0)>0 for group in coverage.get('data',{}).get('covergroups',[]))):
            status,reason='BLOCKED','No sampled functional coverage evidence was produced'
        results.append(dict(name=test['name'],status=status,reason=reason,seed=test['seed'],
                            clock_case=test.get('clock_case'),observed_clock_periods_ps=observed_periods,
                            scoreboard_comparisons=sum(comparisons),uvm_counts=uvm_counts,
                            log=str(directory/'simulation.log'),coverage=coverage,assertion_results=assertion_results))
    report=dict(status='PASS' if results and all(r['status']=='PASS' for r in results) else
                'FAIL' if any(r['status'] in ('FAIL','TIMEOUT') for r in results) else 'BLOCKED',
                tests=results,mode='regress' if regress else 'run',compile=compile_result)
    atomic_write_text(code/'simulation'/f"{report['mode']}.json",json.dumps(report,indent=2)+'\n')
    return report
