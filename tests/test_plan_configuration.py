"""The test plan covers only the build configuration the request selected; what it leaves out stays visible."""
import copy
import json

from dv_agent.codegen.port_comparison import compare
from dv_agent.pipeline import run_testplan_doc
from dv_agent.plan.configuration import apply_interfaces, apply_registers, apply_sections, load_configuration, render
from dv_agent.plan.interfaces import compact, interface_questions
from dv_agent.plan.testplan_doc import unpaired_assertions
from test_testplan_doc import _doc, _llm, run  # noqa: F401  (fixture)

PORTS = [dict(name='wb_adr_i', direction='input', width=3), dict(name='wb_dat_i', direction='input', width=8),
         dict(name='wb_sel_i', direction='input', width=4)]


def config():
    return dict(defines=['DATA_BUS_WIDTH_8'], selected_bits=8, excluded_bits=[], ports=PORTS)


def signal(name, width='1', **fields):
    return dict(dict(name=name, width=width, direction='input', availability='', description='d', active_level='not_applicable',
                     active_level_documented=False, direction_documented=True, width_documented=True), **fields)


def interfaces():
    signals = [signal('WB_ADDR_I', '5 or 3'), signal('WB_DAT_I', '32 or 8'), signal('WB_SEL_I', '4'),
               signal('BAUD_O', availability='Enabled if BAUD_OUTPUT is defined', direction='output')]
    return dict(status='PASS', signals=copy.deepcopy(signals), groups=[dict(
        name='bus', function='f', category='bus', protocol='p', connected_to='c', peer_type='t', dut_role='r', is_sideband=False,
        direction_summary='in', signals=signals)])


def test_no_selected_configuration_changes_nothing(tmp_path):
    assert load_configuration(None) is None and load_configuration(tmp_path / 'missing.json') is None
    path = tmp_path / 'interface.json'
    path.write_text(json.dumps(dict(ports=PORTS)))
    assert load_configuration(path) is None
    before = interfaces()
    apply_interfaces(before, None)
    assert before == interfaces()
    doc = dict(sections=[dict(id='s', entries=[dict(text='32-bit mode')])])
    apply_sections(doc, None)
    assert len(doc['sections'][0]['entries']) == 1 and 'configuration' not in doc and render(doc) == []


def test_the_selection_comes_from_the_interface_defines(tmp_path):
    path = tmp_path / 'interface.json'
    path.write_text(json.dumps(dict(defines=['DATA_BUS_WIDTH_8'], ports=PORTS)))
    loaded = load_configuration(path)
    assert loaded['defines'] == ['DATA_BUS_WIDTH_8'] and loaded['selected_bits'] == 8


def test_signals_show_this_build_and_keep_what_the_specification_documents():
    data = interfaces()
    selected = config()
    apply_interfaces(data, selected)
    by_name = {s['name']: s for s in data['groups'][0]['signals']}
    assert by_name['WB_DAT_I']['configured_width'] == 8 and by_name['WB_DAT_I']['width'] == '32 or 8'  # documented value untouched
    assert by_name['WB_ADDR_I']['configured_width'] == 3  # the name differs from the RTL: the only input of a documented width
    assert by_name['BAUD_O']['inactive_in_configuration'].startswith('Not in this build')
    assert selected['excluded_bits'] == [32]  # '5 or 3' has no selected width in it, so 5 is not treated as another bus mode
    shown = compact(data)[0]['signals']
    assert 'WB_DAT_I[8] input' in shown and 'WB_ADDR_I[3] input' in shown and not any('BAUD_O' in s for s in shown)
    assert not any('BAUD_O' in q['text'] for q in interface_questions(data))


def test_the_port_comparison_sees_the_same_inventory_after_configuration():
    data = interfaces()
    definition = dict(ports=PORTS)
    before = [(r['spec'], r['status'], r.get('issues')) for r in compare(dict(interfaces=data), definition)['rows']]
    apply_interfaces(data, config())
    assert before == [(r['spec'], r['status'], r.get('issues')) for r in compare(dict(interfaces=data), definition)['rows']]


def selected_config():
    selected = config()
    apply_interfaces(interfaces(), selected)
    return selected


def test_registers_of_another_mode_leave_the_map_with_their_fields_and_conflicts():
    selected = selected_config()
    registers = dict(registers=[dict(name='Line', availability=''), dict(name='Debug', availability='When using 32-bit data bus interface')],
                     configurable=[dict(register_name='Line', availability=''), dict(register_name='Debug', availability='')],
                     conflicts=[dict(register='Debug', attribute='access'), dict(register='Line', attribute='access')])
    apply_registers(registers, selected)
    assert [r['name'] for r in registers['registers']] == ['Line']
    assert [f['register_name'] for f in registers['configurable']] == ['Line'] and [c['register'] for c in registers['conflicts']] == ['Line']
    assert selected['inactive_registers'] == [dict(name='Debug', reason='Available only in 32-bit mode')]


def entry(text, kind='check', **fields):
    return dict(dict(text=text, kind=kind, details=[]), **fields)


def test_an_entry_about_another_mode_is_listed_and_its_neighbours_keep_their_places():
    selected = selected_config()
    section = dict(id='features', heading='Features', entries=[entry('Keep one'), entry('32-bit mode is the default'), entry('Keep two'),
                                                                 entry('Keep three', details=['applies on a 32 bit bus']), entry('Word length of 5 bits')],
                   subsections=[dict(entry_indexes=[0, 1, 2]), dict(entry_indexes=[3, 4])])
    doc = dict(sections=[section])
    apply_sections(doc, selected)
    assert [e['text'] for e in section['entries']] == ['Keep one', 'Keep two', 'Word length of 5 bits']
    assert [[section['entries'][i]['text'] for i in sub['entry_indexes']] for sub in section['subsections']] == [['Keep one', 'Keep two'], ['Word length of 5 bits']]
    assert [i['text'] for i in doc['configuration']['excluded_items']] == ['32-bit mode is the default', 'Keep three']
    assert 'cited_chunk_ids' not in str(doc['configuration'])  # the list is never eligible as code input


def test_an_assertion_whose_cover_was_outside_the_configuration_goes_with_it():
    selected = selected_config()
    checks = [entry('a_fine holds', 'assertion'), entry('a_wide holds', 'assertion'), entry('a_never_paired holds', 'assertion')]
    coverage = [entry('c_fine covered', 'cover_property'), entry('c_wide covered on the 32-bit bus', 'cover_property')]
    assert unpaired_assertions(checks, coverage)[0] == ['a_never_paired']
    doc = dict(sections=[dict(id='checks', heading='Checks', entries=checks), dict(id='coverage', heading='Coverage', entries=coverage)])
    apply_sections(doc, selected)
    assert [e['text'] for e in checks] == ['a_fine holds', 'a_never_paired holds']  # only the pair this step broke
    assert [e['text'] for e in coverage] == ['c_fine covered']


def test_the_plan_states_its_configuration_lists_exclusions_and_flags_prose_it_cannot_cut():
    selected = selected_config()
    apply_registers(dict(registers=[dict(name='Debug', availability='32-bit only')]), selected)
    doc = dict(sections=[dict(id='s', heading='S', entries=[entry('32-bit default')]), dict(id='strategy', heading='Strategy', strategy=dict(summary='covers 8/32-bit bus handling'))],
               interfaces=dict(signals=[signal('BAUD_O', inactive_in_configuration='Not in this build: x')]))
    apply_sections(doc, selected)
    text = '\n'.join(render(doc))
    assert 'Build configuration (from the request): DATA_BUS_WIDTH_8' in text and 'Outside this configuration (3 items, not planned)' in text
    assert 'Port BAUD_O' in text and 'Register Debug' in text and '32-bit default' in text
    assert '**NEEDS_REVIEW:** Strategy still mentions 32-bit mode' in text


def test_a_saved_snapshot_keeps_exclusions_when_it_is_saved_again():
    selected = selected_config()
    doc = dict(sections=[dict(id='s', heading='S', entries=[entry('32-bit default')])])
    apply_sections(doc, selected)
    apply_sections(doc, selected)
    assert [i['text'] for i in doc['configuration']['excluded_items']] == ['32-bit default']


def test_every_model_section_receives_the_configuration_and_the_plan_records_it(run, tmp_path):
    path = tmp_path / 'interface_definition.json'
    path.write_text(json.dumps(dict(defines=['DATA_BUS_WIDTH_8'], ports=PORTS)))
    llm = _llm()
    run_testplan_doc(run, llm, mode='graph', rtl_interface_path=path)
    payloads = [p for name, p in llm.calls if name == 'testplan_entries']
    assert payloads and all(p['rtl_configuration']['defines'] == ['DATA_BUS_WIDTH_8'] for p in payloads)
    doc = _doc(run)
    assert doc['configuration']['defines'] == ['DATA_BUS_WIDTH_8']
    assert 'Build configuration (from the request): DATA_BUS_WIDTH_8' in (run / 'testplan_doc.md').read_text()
    calls = len(llm.calls)
    run_testplan_doc(run, llm, mode='graph', rtl_interface_path=path)
    assert _doc(run)['configuration']['defines'] == ['DATA_BUS_WIDTH_8'] and calls <= len(llm.calls)
    run_testplan_doc(run, _llm(), mode='graph')
    assert 'configuration' not in _doc(run)  # a plan for another configuration is not reused


def test_no_configuration_means_no_extra_field_for_the_model(run):
    llm = _llm()
    run_testplan_doc(run, llm, mode='graph')
    assert all('rtl_configuration' not in p for name, p in llm.calls if name == 'testplan_entries') and 'configuration' not in _doc(run)


def test_every_flow_gives_the_plan_step_the_interface():
    from pathlib import Path
    import orchestrator_agent
    for flow in (Path(orchestrator_agent.__file__).parent / 'flows').glob('*.json'):
        plan_steps = [s for s in json.loads(flow.read_text())['steps'] if s['tool'] == 'dv_testplan']
        assert plan_steps and all(s['args']['rtl_interface'] == '${out}/rtl/interface_definition.json' for s in plan_steps)
