"""Saved-plan selection and automatic /code progress, without network calls."""
import json
import os
from pathlib import Path

import pytest

from dv_agent.core.progress import emit, emit_event, reporting
from orchestrator_agent.code_run import execute
from orchestrator_agent.saved_runs import latest_successful
from orchestrator_agent.tui import Dashboard


@pytest.mark.parametrize('columns', [40, 60, 80, 120])
def test_current_task_wraps_without_losing_status_or_details(tmp_path, monkeypatch, columns):
    from orchestrator_agent import tui
    monkeypatch.setattr(tui.shutil, 'get_terminal_size', lambda fallback: os.terminal_size((columns, 40)))
    frames = []
    dash = Dashboard(tmp_path, frames.append, ansi=True)
    dash.task_name = 'code_interface_infrastructure_assessment_with_a_very_long_identifier'
    dash.task_detail = ('Missing documented reset polarity; waiting for human acknowledgement.\n'
                        'Reference: /a/very/long/path/to/the/interface_definition.json')
    dash.current = {'step': 'testplan'}
    dash._retry(('tool', 'testplan'), 'WAITING_HUMAN')
    dash.task_fraction = (12345, 67890)
    dash.redraw()
    frame = tui.ANSI.sub('', frames[-1]).replace('\x1b[2J\x1b[H', '')
    pane_width = columns - 4 if columns < 80 else max(28, columns // 3)
    middle = dash._middle(pane_width)
    assert all(len(line) <= pane_width for line in middle)
    start, end = middle.index('current task') + 1, middle.index('task progress')
    contents = ''.join(''.join(middle[start:end]).split())
    for text in (dash.task_name, dash.task_detail, 'WAITING_HUMAN/RETRY(1)'):
        assert ''.join(text.split()) in contents
    assert '…' not in ''.join(middle)
    assert all(len(line) <= columns for line in frame.splitlines())
    # Check the actual rendered cells as well as the panel helper.
    rendered = '\n'.join(line.split('|')[1 if columns < 80 else 2]
                         for line in frame.splitlines() if line.startswith('|'))
    assert dash.task_name in ''.join(rendered.split())
    assert ''.join(dash.task_detail.split()) in ''.join(rendered.split())


def saved(root, name, *, repo=None, status='PASS', authority='DOCUMENTED'):
    out = root / name
    repo = repo or root / 'design'
    repo.mkdir(parents=True, exist_ok=True)
    rtl = repo / 'top.sv'
    rtl.write_text('module top; endmodule')
    (out / 'dv').mkdir(parents=True)
    (out / 'rtl').mkdir()
    (out / 'dv/testplan_doc.json').write_text(json.dumps(dict(
        generation_status='COMPLETE', source_authority=authority,
        sections=[dict(id='stimulus', status=status)])))
    (out / 'rtl/interface_definition.json').write_text('{}')
    variables = dict(repo=str(repo), rtl_top='top', rtl_files=[str(rtl)], rtl_graph_files=[str(rtl)])
    (out / 'orchestrator_ask.json').write_text(json.dumps(dict(variables=variables, requirement='Verify design')))
    (out / 'orchestrator_result.json').write_text('{"status":"PASS"}')
    return out, variables


def test_latest_selection_filters_partial_inferred_other_design_and_missing_sources(tmp_path):
    root = tmp_path / 'runs'
    older, variables = saved(root, 'older')
    newer, _ = saved(root, 'newer')
    os.utime(older / 'dv/testplan_doc.json', (1, 1))
    assert latest_successful(root)[0] == newer
    saved(root, 'partial', status='BLOCKED')
    saved(root, 'rtl_inferred', authority='RTL_INFERRED')
    other, _ = saved(root, 'other', repo=root/'other_design')
    assert latest_successful(root, variables)[0] == newer
    assert latest_successful(root, dict(repo=str(root/'unknown'))) is None
    (root / 'malformed/dv').mkdir(parents=True)
    (root / 'malformed/dv/testplan_doc.json').write_text('[]')
    assert latest_successful(root, variables)[0] == newer
    (newer / 'orchestrator_result.json').write_text('{"status":"BLOCKED"}')
    assert latest_successful(root, variables)[0] == older
    Path(variables['rtl_graph_files'][0]).unlink()
    assert latest_successful(root, variables) is None
    assert latest_successful(root)[0] == other


def test_repl_code_restores_plan_without_replanning_and_fresh_disables_restore(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    out, variables = saved(tmp_path/'runs', 'saved')
    monkeypatch.setattr(terminal, 'PACKAGE_ROOT', tmp_path)
    monkeypatch.setattr(terminal, '_default_out', lambda: tmp_path/'runs/new')
    def no_plan(*a, **kw):
        pytest.fail('restored /code must not rerun /plan')
    monkeypatch.setattr(terminal, 'run_flow', no_plan)
    calls = []
    monkeypatch.setattr(terminal, 'build_code', lambda directory, selected, **kw:
                        calls.append((directory, selected)) or
                        dict(code_dir='code', policy=dict(kept=1, skipped=0), tests=[dict(name='basic')]))
    def script(lines):
        iterator = iter(lines)
        def read(_):
            try: return next(iterator)
            except StopIteration: raise EOFError
        return read
    shown = []
    terminal.repl(input_fn=script(['/code']), output_fn=shown.append, llm=object())
    assert calls == [(out, variables)]
    assert 'Using saved successful testplan:' in '\n'.join(shown)
    assert 'Collate completed feature algorithms' in '\n'.join(shown)
    terminal.repl(input_fn=script(['/fresh', '/code']), output_fn=shown.append, llm=object())
    assert len(calls) == 1
    assert 'Code blocked: no testplan' in '\n'.join(shown)


@pytest.mark.parametrize('outcome', ['PASS', 'BLOCKED', 'interrupt', 'error'])
def test_code_operation_persists_progress_and_restores_callers_sinks(tmp_path, outcome):
    out, variables = saved(tmp_path/'runs', 'saved')
    parent, frames = [], []
    def build(*args, **kwargs):
        from dv_agent.codegen.events import stage
        emit_event('substeps_configured', steps=[dict(id='feature', label='Implement storage')])
        with stage('feature', 'Implement storage'):
            emit('Writing monitor-fed coverage')
            if outcome == 'interrupt': raise KeyboardInterrupt
            if outcome == 'error': raise ValueError('Missing evidence')
        return dict(compile=dict(status=outcome))
    with reporting(sink=parent.append, event_sink=parent.append):
        if outcome in ('interrupt', 'error'):
            with pytest.raises(KeyboardInterrupt if outcome == 'interrupt' else ValueError):
                execute(build, out, variables, llm=object(), show=frames.append, dashboard=True, ansi=True)
        else:
            execute(build, out, variables, llm=object(), show=frames.append, dashboard=True, ansi=True)
        emit('caller restored')
        emit_event('caller_event')
    assert parent == ['caller restored', {'kind':'caller_event'}]
    result = json.loads((out/'code_result.json').read_text())
    assert result['status'] == dict(interrupt='INTERRUPTED', error='BLOCKED').get(outcome, outcome)
    events = [json.loads(row) for row in (out/'code_trace.jsonl').read_text().splitlines()]
    assert events[0]['event'] == 'run_start' and events[-1]['event'] == 'run_finish'
    assert any(e.get('id') == 'feature' and e['event'] == 'substep_start' for e in events)
    assert 'current task' in '\n'.join(frames) and 'Implement storage' in '\n'.join(frames)
    assert result['elapsed_s'] >= 0


def test_code_dashboard_dynamic_steps_preserve_finished_status_without_heartbeat(tmp_path, monkeypatch):
    import orchestrator_agent.tui as tui
    clock = [10.0]
    monkeypatch.setattr(tui.time, 'monotonic', lambda: clock[0])
    dash = Dashboard(tmp_path, lambda frame: None, flow=dict(steps=[dict(id='code')]),
                     substep_owner='code', substeps=[('code_grouping', 'Group')], ansi=True)
    dash.handle(dict(event='substep_done', id='code_grouping', status='PASS'))
    dash.handle(dict(event='substeps_configured', steps=[dict(id='code_grouping', label='Group'),
        dict(id='code_pseudocode:storage', label='Understand storage')]))
    assert dash.substatus['code_grouping'] == 'PASS'
    clock[0] = 25.0
    dash.handle(dict(event='substep_start', id='code_pseudocode:storage', label='Understand storage'))
    assert dash.elapsed_s == 0
    assert '50%' in '\n'.join(dash._middle(40))
    dash.handle(dict(event='substep_done', id='code_pseudocode:storage', status='PASS'))
    assert dash.elapsed_s == 15
    assert '100%' in '\n'.join(dash._middle(40))


def test_retry_preserves_old_status_counts_each_attempt_and_finishes_cleanly(tmp_path):
    flow=dict(steps=[dict(id='code')])
    dash=Dashboard(tmp_path,lambda frame:None,flow=flow,substep_owner='code',substeps=[('clock','Clock')],ansi=True)
    dash.handle(dict(event='tool_start',step='code',tool='code',attempt=1))
    dash.handle(dict(event='substep_start',id='clock',label='Clock'))
    dash.handle(dict(event='substep_done',id='clock',status='BLOCKED'))
    dash.handle(dict(event='substep_start',id='clock',label='Clock'))
    assert 'BLOCKED/RETRY(1)' in '\n'.join(dash._right(42))
    assert 'BLOCKED/RETRY(1)' in '\n'.join(dash._middle(42))
    assert dash.substatus['clock']=='RUN' and '0%' in '\n'.join(dash._middle(42))
    dash.handle(dict(event='task_retry',status='TIMEOUT',attempt=3))
    assert 'TIMEOUT/RETRY(2)' in '\n'.join(dash._right(42))
    dash.handle(dict(event='substep_done',id='clock',status='PASS'))
    assert '/RETRY' not in '\n'.join(dash._right(42))
    assert '100%' in '\n'.join(dash._middle(42))


def test_tool_retry_start_does_not_double_count_and_success_is_not_retry(tmp_path):
    shown=[]
    dash=Dashboard(tmp_path,shown.append,flow=dict(steps=[dict(id='build')]),ansi=False)
    dash.handle(dict(event='tool_start',step='build',tool='build',attempt=1))
    dash.handle(dict(event='tool_done',step='build',status='FAIL'))
    dash.handle(dict(event='tool_retry',step='build',status='FAIL',next_attempt=2))
    dash.handle(dict(event='tool_start',step='build',tool='build',attempt=2))
    assert shown[-1]=='[FAIL/RETRY(1)] build: build'
    assert 'FAIL/RETRY(1)' in '\n'.join(dash._right(40))
    dash.handle(dict(event='tool_done',step='build',status='PASS'))
    dash.handle(dict(event='tool_start',step='build',tool='build',attempt=3))
    assert shown[-1]=='[run] build: build'


def test_manual_retry_restores_failure_and_number_from_saved_trace(tmp_path):
    events=[dict(event='tool_start',step='code'),dict(event='substep_start',id='clock'),
            dict(event='substep_done',id='clock',status='FAIL'),dict(event='tool_done',step='code',status='BLOCKED'),
            dict(event='tool_start',step='code'),dict(event='substep_start',id='clock'),
            dict(event='substep_done',id='clock',status='TIMEOUT'),dict(event='tool_done',step='code',status='BLOCKED')]
    (tmp_path/'code_trace.jsonl').write_text('\n'.join(json.dumps(e) for e in events)+'\nnot json\n')
    dash=Dashboard(tmp_path,lambda frame:None,flow=dict(steps=[dict(id='code')]),
                   substep_owner='code',substeps=[('clock','Clock')],ansi=True)
    dash.handle(dict(event='run_start',steps=['code']))
    dash.handle(dict(event='tool_start',step='code',tool='code',attempt=1))
    dash.handle(dict(event='substep_start',id='clock',label='Clock'))
    frame='\n'.join(dash._right(45))
    assert 'BLOCKED/RETRY(2)' in frame and 'TIMEOUT/RETRY(2)' in frame
