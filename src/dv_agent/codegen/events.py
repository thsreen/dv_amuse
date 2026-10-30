"""Code generation phases shared by the library, terminal preview and dashboard."""
from contextlib import contextmanager

from ..core.progress import emit_event

STEPS=[
    ('code_selection','Select saved plan and RTL interface'),
    ('code_grouping','Plan clock, reset, interfaces and small feature tasks'),
    ('code_dependencies','Collate cross-group dependencies'),
    ('code_pseudocode','Retrieve excerpts and write feature pseudocode'),
    ('code_collation','Collate the implementation pseudocode'),
    ('code_foundation','Build reusable interfaces and configuration'),
    ('code_feature','Implement stimulus, checks and monitor coverage'),
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
                   status='INTERRUPTED' if isinstance(exc,KeyboardInterrupt) else 'FAIL',error_type=type(exc).__name__)
        raise
    else: emit_event('substep_done',id=stage_id,label=label,**result)


def skip(*stage_ids):
    for sid in stage_ids: emit_event('substep_done',id=sid,label=dict(STEPS).get(sid,sid),status='NOT_RUN')


def feature_steps(waves,tasks):
    steps=[]
    for sid,label in STEPS:
        if sid in ('code_pseudocode','code_feature'):
            for wave in waves:
                for tid in wave:
                    steps.append((sid+':'+tid,('Understand ' if sid=='code_pseudocode' else 'Implement ')+tasks[tid].title))
        else: steps.append((sid,label))
    emit_event('substeps_configured',steps=[dict(id=sid,label=label) for sid,label in steps])
