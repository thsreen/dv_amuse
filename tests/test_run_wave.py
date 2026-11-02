"""/run wave asks the simulator for a waveform, and every run reports its coverage."""
from pathlib import Path

from dv_agent.codegen.simulator import command, coverage_markdown, coverage_summary


LOG = '''
UVM_INFO @ 5: uvm_test_top.cmn_env.plan_cov_a [PLAN_COVERAGE] a samples=3 coverage=100.00
UVM_INFO @ 5: uvm_test_top.cmn_env.plan_cov_b [PLAN_COVERAGE] b samples=0 coverage=0.00
UVM_INFO @ 5: uvm_test_top.cmn_env.bus.cov [OBSERVED_COVERAGE] bus samples=8 coverage=50.00
UVM_INFO @ 5: uvm_test_top.cmn_env.system_cov [SYSTEM_COVERAGE] samples=4 coverage=25.00
[PLAN_COVERAGE]    2
'''


def test_coverage_summary_reads_each_group_and_averages_only_plan_groups():
    summary = coverage_summary(LOG, [dict(status='PASS'), dict(status='FAIL')])
    assert [(g['kind'], g['name'], g['samples'], g['percent']) for g in summary['groups']] == [
        ('plan', 'a', 3, 100.0), ('plan', 'b', 0, 0.0), ('observed', 'bus', 8, 50.0), ('system', 'system', 4, 25.0)]
    assert (summary['plan_groups'], summary['plan_average'], summary['plan_full'], summary['plan_unsampled']) == (2, 50.0, 1, 1)
    assert (summary['assertions_passed'], summary['assertions']) == (1, 2)
    text = coverage_markdown('t', summary)
    assert '| b | plan | 0 | 0.00% |' in text and 'Assertions passed: 1 of 2' in text


def test_a_log_without_coverage_lines_reports_no_average():
    summary = coverage_summary('nothing here', [])
    assert summary['plan_average'] is None and summary['groups'] == []


def test_the_waveform_option_is_only_added_when_asked_for(tmp_path):
    (tmp_path / 'lib').mkdir()
    manifest = dict(code_dir=str(tmp_path), rtl_files=[], compile_files=[], defines=[])
    capabilities = dict(binary='xezim', uvm=str(tmp_path / 'lib/uvm_pkg.sv'))
    test = dict(name='t', seed=1)
    assert '--fst' not in command(manifest, capabilities, simulate=True, test=test)
    cmd = command(manifest, capabilities, simulate=True, test=test, waveform=tmp_path / 't.fst')
    assert cmd[cmd.index('--fst') + 1] == str(tmp_path / 't.fst')


def test_repl_routes_run_wave_and_shows_the_waveform_and_coverage(monkeypatch, tmp_path):
    from orchestrator_agent import repl as terminal
    calls = []
    def run_tests(out, regress=False, wave=False):
        calls.append((regress, wave))
        return dict(status='PASS', tests=[dict(name='t', status='PASS', reason='ok', log='t.log', waveform='t.fst' if wave else None,
                                               coverage_report='r.md', coverage_summary=dict(plan_groups=2, plan_average=50.0, plan_full=1, plan_unsampled=1,
                                                                                            assertions_passed=3, assertions=3))])
    monkeypatch.setattr(terminal, 'run_tests', run_tests)
    lines = iter(['/run wave', '/run'])
    def read(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError
    shown = []
    assert terminal.repl(input_fn=read, output_fn=shown.append, llm_mode='off') == 0
    text = '\n'.join(shown)
    assert calls == [(False, True), (False, False)]
    assert 'waveform: t.fst' in text and 'run wave: PASS' in text and 'coverage report: r.md' in text
    assert 'simple average 50.0%' in text and 'assertions 3 of 3' in text


def test_a_saved_compile_result_from_before_waveforms_still_offers_them(tmp_path, monkeypatch):
    import json
    from dv_agent.codegen import simulator
    report = dict(status='PASS', version='v', uvm='u', binary='xezim', waveform=True)
    monkeypatch.setattr(simulator, 'discover', lambda: dict(report))
    (tmp_path / 'compile_result.json').write_text(json.dumps(dict(status='PASS', fingerprint='bvu', binary='xezim', version='v', uvm='u')))
    result = simulator.compile_project(dict(code_dir=str(tmp_path), build_id='b'))
    assert result['reused'] and result['waveform'] is True and result['fingerprint'] == 'bvu'


def test_run_wave_says_why_when_there_is_no_waveform(monkeypatch):
    from orchestrator_agent import repl as terminal
    monkeypatch.setattr(terminal, 'run_tests', lambda out, regress=False, wave=False: dict(status='PASS', tests=[
        dict(name='t', status='PASS', reason='ok', waveform=None, waveform_reason='The simulator does not offer --fst')]))
    lines = iter(['/run wave'])
    def read(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError
    shown = []
    terminal.repl(input_fn=read, output_fn=shown.append, llm_mode='off')
    assert 'waveform: not produced: The simulator does not offer --fst' in '\n'.join(shown)
