"""Execute the automatic coding operation with the same dashboard as planning."""
import json
import time
from datetime import datetime, timezone

from dv_agent.codegen.events import STEPS, stage, skip
from dv_agent.core.fsutil import atomic_write_text
from dv_agent.core.progress import reporting

from .tui import Dashboard


def preview(out):
    return '\n'.join(['--- code preview ---', f'Testplan: {out / "dv/testplan_doc.json"}',
                      '/code will execute automatically:'] +
                     [f'  {i}. {label}.' for i, (_, label) in enumerate(STEPS, 1)] +
                     [f'Output: {out / "code"}',
                      'Dependency notes and pseudocode are saved along the way. Use /run afterward.'])


def execute(build, out, variables, *, llm, show, dashboard=False, ansi=False):
    out.mkdir(parents=True, exist_ok=True)
    flow = dict(steps=[dict(id='code', tool='dv_agent.codegen', description='Generate verification code')],
                policy=dict(max_total_tool_calls=1, max_overrides=0))
    # Noninteractive output also receives phase events, without screen repainting.
    dash = Dashboard(out, show, flow=flow, title='Code from saved testplan',
                     ansi=dashboard and ansi, substeps=STEPS, substep_owner='code')
    started = time.monotonic()

    def event(kind, **fields):
        row = dict(event=kind, timestamp=datetime.now(timezone.utc).isoformat(), **fields)
        with (out / 'code_trace.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row) + '\n')
        dash.handle(row)

    def finish(status, reason):
        result = dict(status=status, reason=reason, elapsed_s=round(time.monotonic()-started, 3))
        atomic_write_text(out / 'code_result.json', json.dumps(result, indent=2)+'\n')
        event('tool_done', step='code', summary=reason, **result)
        event('run_finish', **result)

    event('run_start', steps=['code'])
    event('tool_start', step='code', tool='dv_agent.codegen', attempt=1)
    try:
        with reporting(sink=lambda message: event('task_progress', step='code', message=message),
                       event_sink=lambda detail: event(detail['kind'], **{k:v for k,v in detail.items() if k!='kind'})):
            with stage('code_selection'):
                if not (out / 'dv/testplan_doc.json').is_file():
                    raise ValueError('No saved testplan; run /plan first')
            if llm is None and not variables.get('code_contract'):
                skip(*(sid for sid, _ in STEPS[1:] if sid != 'code_render'))
                with stage('code_render'):
                    result = build(out, variables, llm=llm)
            else:
                result = build(out, variables, llm=llm)
        compile_status = result.get('compile', {}).get('status', 'NOT_RUN')
        status = 'PASS' if compile_status in ('PASS', 'NOT_RUN') else 'BLOCKED'
        finish(status, f'Code saved; compile {compile_status}. Generated expectations require review.')
        return result
    except BaseException as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        finish('INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'BLOCKED', reason)
        raise
