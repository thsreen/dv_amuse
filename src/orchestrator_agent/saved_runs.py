"""Select a complete compatible saved plan; never silently switch a selected design."""
import json
from pathlib import Path


def _identity_matches(saved, selected):
    if selected.get('rtl_top') and saved.get('rtl_top')!=selected['rtl_top']: return False
    chosen={str(Path(p).resolve()) for p in selected.get('rtl_files',[])}
    previous={str(Path(p).resolve()) for p in saved.get('rtl_files',[])}
    if chosen: return bool(chosen & previous)
    if selected.get('repo'):
        repo=Path(selected['repo']).resolve()
        return Path(saved.get('repo','')).resolve()==repo or bool(previous) and all(Path(p).is_relative_to(repo) for p in previous)
    return True


def latest_successful(runs_root, selected=None):
    root=Path(runs_root).resolve();matches=[]
    if not root.is_dir(): return None
    for directory in root.iterdir():
        if not directory.is_dir() or not directory.resolve().is_relative_to(root): continue
        try:
            plan_path=directory/'dv/testplan_doc.json'
            plan=json.loads(plan_path.read_text())
            sections=plan.get('sections',[])
            if not sections or plan.get('generation_status','COMPLETE')!='COMPLETE': continue
            if plan.get('source_authority','DOCUMENTED')!='DOCUMENTED': continue
            if not all(s.get('status')=='PASS' or (s.get('generator')=='rtl_observations' and s.get('status')=='NOT_RUN') for s in sections): continue
            result=directory/'orchestrator_result.json'
            if result.is_file() and json.loads(result.read_text()).get('status')!='PASS': continue
            ask=json.loads((directory/'orchestrator_ask.json').read_text());variables=ask['variables']
            if not variables.get('repo') or not variables.get('rtl_top'): continue
            files=variables.get('rtl_graph_files',[])
            if not files or not all(isinstance(p,str) and Path(p).is_absolute() and Path(p).is_file() for p in files): continue
            if not (directory/'rtl/interface_definition.json').is_file(): continue
            if not _identity_matches(variables,selected or {}): continue
            matches.append((plan_path.stat().st_mtime,directory,ask))
        except (OSError,ValueError,KeyError,TypeError,AttributeError): continue
    if not matches: return None
    _,directory,ask=max(matches,key=lambda row:(row[0],str(row[1])))
    return directory,ask


def matches_current_run(directory, variables):
    path=Path(directory)/'orchestrator_ask.json'
    if not path.is_file(): return True
    try: return _identity_matches(json.loads(path.read_text())['variables'],variables)
    except (OSError,ValueError,KeyError,TypeError): return False
