"""Code generation phases shared by the library, terminal preview and dashboard."""
from contextlib import contextmanager

from ..core.progress import emit_event

PORT_STEPS=[('code_port_comparison','Compare specification ports with RTL ports'),
            ('code_port_validation','Independently validate specification/RTL comparison')]

STEPS=[
    ('code_selection','Select saved plan and RTL interface'),
    ('code_binding','Clock and reset: bind ports, reset level and timing (no model call)'),
    ('code_common','Common UVC: copy the clock and reset UVCs and the common agent and environment'),
    ('code_interfaces','Identify interface groups'),
    ('code_interface','Each interface: scaffold, assess needs, then build selected infrastructure'),
    ('code_grouping','Group small tasks by interface or feature'),
    ('code_dependencies','Analyze sequence extension, sequencer controls and ordering'),
    ('code_pseudocode','Write pseudocode for one feature'),
    ('code_feature','Implement and validate that feature before the next'),
    ('code_collation','Collate completed feature algorithms'),
    ('code_integration','Compose sequences and executable tests'),
    ('code_validation','Validate evidence, ownership and widths'),
    ('code_review','Review source-backed implementation'),
    ('code_hooks','Implement declared protocol extensions'),
    ('code_render','Render reusable SystemVerilog templates'),
    ('code_publish','Save code, tests and traceability'),
]


@contextmanager
def stage(stage_id,label=None):
    label=label or dict(STEPS).get(stage_id,stage_id)
    emit_event('substep_start',id=stage_id,label=label)
    result={'status':'PASS'}
    try:
        yield result
    except BaseException as exc:
        emit_event('substep_done',id=stage_id,label=label,
                   status=getattr(exc,'status','INTERRUPTED' if isinstance(exc,KeyboardInterrupt) else 'FAIL'),error_type=type(exc).__name__)
        raise
    else: emit_event('substep_done',id=stage_id,label=label,**result)


def skip(*stage_ids):
    for sid in stage_ids: emit_event('substep_done',id=sid,label=dict(STEPS).get(sid,sid),status='NOT_RUN')


def feature_steps(waves,tasks,unit_rows=()):
    steps=[STEPS[0]]+PORT_STEPS
    groups={}   # interface name -> its title and steps, in execution (smallest-first) order
    for row in unit_rows:
        tid=row['id']
        if not tid.startswith(('foundation_','interface_','collateral_','assessment_')): continue
        if tid.startswith('foundation_'):
            # Clock and reset are two fixed steps shared by every design, not one model-driven unit each.
            if not any(sid=='code_binding' for sid,_ in steps): steps += [STEPS[1],STEPS[2]]
            continue
        if tid.startswith('interface_') and not any(sid=='code_interfaces' for sid,_ in steps):
            steps.append(('code_interfaces','Identify interface groups'))
        name=tid.split('_',1)[1]
        group=groups.setdefault(name,dict(title=row['title'].removesuffix(' collateral'),steps={}))
        if tid.startswith('assessment_'): group['steps']['needs']=('code_interface_needs:'+name,'Assess what the testbench needs')
        elif tid.startswith('interface_'): group['steps']['base']=('code_interface_base:'+tid,'Bind ports and their evidence')
        else:
            group['steps']['infra']=('code_infrastructure:'+tid,'Plan the collateral')
            group['steps']['build']=('code_interface:'+tid,'Build and validate the collateral')
    parent={}
    for name,group in groups.items():
        header=('group:'+name,'Interface '+group['title'])
        steps.append(header)
        for key in ('base','needs','infra','build'):
            if key in group['steps']:
                steps.append(group['steps'][key]);parent[group['steps'][key][0]]=header[0]
    if not unit_rows: steps+=STEPS[1:5]
    elif not any(sid=='code_interfaces' for sid,_ in steps): steps.append(('code_interfaces','Identify interface groups'))
    for sid,label in STEPS[5:]:
        if sid=='code_pseudocode':
            for wave in waves:
                for tid in wave:
                    steps.append(('code_pseudocode:'+tid,'Understand '+tasks[tid].title))
                    steps.append(('code_feature:'+tid,'Implement '+tasks[tid].title))
            if not tasks: steps.append((sid,label))
        elif sid=='code_feature':
            if not tasks: steps.append((sid,label))
        else: steps.append((sid,label))
    emit_event('substeps_configured',steps=[dict(id=sid,label=label,**({'parent':parent[sid]} if sid in parent else {})) for sid,label in steps])
