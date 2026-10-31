import copy
import json

import pytest

from dv_agent.codegen.interface_context import scoped
from dv_agent.codegen.port_comparison import compare
from dv_agent.codegen.port_validation import validate_comparison, validated
from test_port_comparison import sample
from test_codegen import inputs


def test_validator_checks_raw_comparison_without_using_its_helpers(monkeypatch):
    plan,rtl=sample()
    report=compare(plan,rtl,validate=False)
    def forbidden(*args,**kwargs): raise AssertionError('Comparator helper was called')
    monkeypatch.setattr('dv_agent.codegen.port_comparison.compare',forbidden)
    monkeypatch.setattr('dv_agent.codegen.port_comparison.width',forbidden)
    monkeypatch.setattr('dv_agent.codegen.interface_context.relationships',forbidden)
    assert validate_comparison(plan,rtl,report)['status']=='PASS'


@pytest.mark.parametrize('fault',['omitted','duplicate','invented','width','direction','source','context_width',
                                'context_quote','context_polarity','context_responsibility','stale','decision','authority'])
def test_false_pass_or_corrupted_report_is_rejected(fault):
    plan,rtl=sample()
    report=compare(plan,rtl)
    row=report['rows'][0];context=report['relationship_context']['ports'][0]
    if fault=='omitted':report['rows']=[]
    if fault=='duplicate':report['rows'].append(copy.deepcopy(row))
    if fault=='invented':row['rtl']='imaginary'
    if fault=='width':row['rtl_width']=32
    if fault=='direction':row['rtl_direction']='output'
    if fault=='source':row['source_id']='fabricated'
    if fault=='context_width':context['width']=32
    if fault=='context_quote':context['specification']['quote']='fabricated'
    if fault=='context_polarity':context['specification']['active_level']='low'
    if fault=='context_responsibility':context['testbench_responsibility']='observe'
    if fault=='stale':rtl['sources']=['different.sv']
    if fault=='decision':report['review_decisions']={'reviewer':'pretend'}
    if fault=='authority':report['relationship_context']['authority']='RTL behavior is authoritative'
    assert validate_comparison(plan,rtl,report)['status']=='BLOCKED'
    if fault!='stale': assert not validated(report)


def test_independent_width_evaluator_catches_fault_in_producer(monkeypatch):
    plan,rtl=sample();rtl['ports'][0]['width']=16
    monkeypatch.setattr('dv_agent.codegen.port_comparison.width',lambda value:8)
    assert compare(plan,rtl,validate=False)['status']=='PASS'  # deliberately faulty producer
    report=compare(plan,rtl)
    assert report['status']==report['independent_validation']['status']=='BLOCKED'
    assert any('source widths differ' in issue for issue in report['independent_validation']['issues'])
    assert scoped(report,['data_i'])=={}


def test_unsigned_legacy_or_changed_audit_cannot_supply_context():
    plan,rtl=sample();report=compare(plan,rtl)
    assert validated(report)
    assert scoped(report,['data_i'])['ports']
    report.pop('independent_validation')
    assert scoped(report,['data_i'])=={}


def test_validator_detects_context_provenance_promotion():
    plan,rtl=sample()
    plan['interfaces']['groups']=[dict(name='Data',signals=plan['interfaces']['signals'],
        property_evidence={'name':dict(provenance='INFERRED',quote='Proposed group',cited_chunk_ids=['CH-spec'])})]
    report=compare(plan,rtl)
    report['relationship_context']['groups'][0]['property_evidence']['name']['provenance']='DOCUMENTED'
    assert validate_comparison(plan,rtl,report)['status']=='BLOCKED'


def test_group_bindings_cannot_contradict_primary_spec_inventory():
    plan,rtl=sample()
    member=dict(plan['interfaces']['signals'][0],direction='output')
    plan['interfaces']['groups']=[dict(name='Data',signals=[member])]
    report=compare(plan,rtl)
    assert report['status']=='BLOCKED'
    assert any('group direction contradicts' in issue for issue in report['independent_validation']['issues'])


def test_independent_failure_stops_before_sv_and_has_own_report(inputs,monkeypatch):
    from dv_agent.codegen import build_project
    from dv_agent.codegen import interface_context
    root,_,_,_,source=inputs
    real=interface_context.relationships
    def corrupted(*args,**kwargs):
        result=real(*args,**kwargs)
        result['ports'][0]['dut_direction']='output'
        return result
    monkeypatch.setattr(interface_context,'relationships',corrupted)
    with pytest.raises(ValueError,match='port comparison BLOCKED'):
        build_project(root/'plan.json',root/'interface.json',root/'output',contract_path=root/'contract.json',rtl_files=[source])
    audit=json.loads((root/'output/interface_port_validation.json').read_text())
    assert audit['status']=='BLOCKED' and any('relationship binding changed' in s for s in audit['issues'])
    assert (root/'output/interface_port_validation.md').is_file()
    assert not list((root/'output').rglob('*.sv'))
    assert not list((root/'output').rglob('*.svh'))
