"""Interface steps are grouped as sub-bullets under one header per interface, smallest interface first."""
import re

from dv_agent.codegen.events import feature_steps
from dv_agent.core.progress import reporting
from orchestrator_agent.tui import Dashboard

ROWS = [dict(id='foundation_clock', title='Clock'), dict(id='foundation_reset', title='Reset'),
        dict(id='interface_narrow', title='Narrow bus'), dict(id='interface_wide', title='Wide bus'),
        dict(id='assessment_narrow', title='Assess narrow'), dict(id='collateral_narrow', title='Narrow bus collateral'),
        dict(id='assessment_wide', title='Assess wide'), dict(id='collateral_wide', title='Wide bus collateral')]


def configured():
    events = []
    with reporting(event_sink=lambda detail: events.append(detail)):
        feature_steps([], {}, ROWS)
    return next(e for e in events if e['kind'] == 'substeps_configured')['steps']


def test_each_interface_is_a_header_with_its_four_steps_as_sub_bullets_in_run_order():
    steps = configured()
    ids = [s['id'] for s in steps]
    assert ids.index('group:narrow') < ids.index('group:wide')
    narrow = [s for s in steps if s.get('parent') == 'group:narrow']
    assert [s['id'] for s in narrow] == ['code_interface_base:interface_narrow', 'code_interface_needs:narrow',
                                         'code_infrastructure:collateral_narrow', 'code_interface:collateral_narrow']
    assert all(ids.index(s['id']) > ids.index('group:narrow') for s in narrow)
    assert 'parent' not in next(s for s in steps if s['id'] == 'group:narrow')


def dashboard(lines, ansi):
    dash = Dashboard('.', lines.append, flow=dict(steps=[dict(id='code', tool='dv_agent.codegen', description='Code')], policy={}),
                     ansi=ansi, substeps=[], substep_owner='code')
    dash.handle(dict(event='run_start', steps=['code']))
    dash.handle(dict(event='substeps_configured', steps=configured()))
    return dash


def test_the_header_status_follows_its_sub_steps_and_indents_them():
    dash = dashboard([], ansi=False)
    dash.handle(dict(event='substep_done', id='code_interface_base:interface_narrow', status='PASS'))
    dash.handle(dict(event='substep_start', id='code_interface_needs:narrow'))
    right = [re.sub(r'\x1b\[[0-9;]*m', '', row) for row in dash._right(70)]
    header = next(r for r in right if 'Interface Narrow bus' in r)
    assert header.startswith('  ') and not header.startswith('    ') and header.rstrip().endswith('RUN')
    child = next(r for r in right if 'Bind ports and their evidence' in r)
    assert child.startswith('    ') and child.rstrip().endswith('PASS')
    assert next(r for r in right if 'Interface Wide bus' in r).rstrip().endswith('....')
    for sid in ('code_interface_needs:narrow', 'code_infrastructure:collateral_narrow', 'code_interface:collateral_narrow'):
        dash.handle(dict(event='substep_done', id=sid, status='PASS'))
    right = [re.sub(r'\x1b\[[0-9;]*m', '', row) for row in dash._right(70)]
    assert next(r for r in right if 'Interface Narrow bus' in r).rstrip().endswith('PASS')
    dash.handle(dict(event='substep_done', id='code_infrastructure:collateral_wide', status='BLOCKED'))
    right = [re.sub(r'\x1b\[[0-9;]*m', '', row) for row in dash._right(70)]
    assert next(r for r in right if 'Interface Wide bus' in r).rstrip().endswith('BLOCKED')


def test_plain_progress_lines_show_sub_bullets():
    lines = []
    dash = dashboard(lines, ansi=False)
    lines.clear()
    dash.handle(dict(event='substep_start', id='code_interface_needs:narrow', label='Assess what the testbench needs'))
    assert lines == ['[run] ' + '  - Assess what the testbench needs']
    lines.clear()
    dash.handle(dict(event='substeps_configured', steps=configured()))
    assert '  * Interface Narrow bus' in lines[0] and '    - Bind ports and their evidence' in lines[0]
