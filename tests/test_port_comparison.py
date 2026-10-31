import copy
import json
import pytest
from dv_agent.codegen.port_comparison import compare
from dv_agent.quality.human_review import sha
from test_codegen import inputs


def sample():
    plan=dict(interfaces=dict(status='PASS',signals=[dict(name='DATA_I',width='[7:0]',direction='input',chunk_id='CH-spec')]))
    rtl=dict(direction_reference='DUT',ports=[dict(name='data_i',width=8,direction='input')])
    return plan,rtl


def decision(plan,rtl,**fields):
    return dict(spec_hash=sha(plan['interfaces']),rtl_hash=sha(rtl),reviewer='Engineer',reason='Reviewed selected configuration',**fields)


def test_independent_matching_and_no_input_mutation():
    plan,rtl=sample();before=copy.deepcopy((plan,rtl))
    assert compare(plan,rtl)['status']=='PASS'
    assert (plan,rtl)==before


@pytest.mark.parametrize('kind',['width','direction','missing','extra','unknown','unproven','reference'])
def test_discrepancies_block(kind):
    plan,rtl=sample()
    if kind=='width':rtl['ports'][0]['width']=16
    if kind=='direction':rtl['ports'][0]['direction']='output'
    if kind=='missing':rtl['ports']=[]
    if kind=='extra':rtl['ports'].append(dict(name='extra',width=1,direction='input'))
    if kind=='unknown':plan['interfaces']['signals'][0]['width']='PARAMETER'
    if kind=='unproven':plan['interfaces']['signals'][0]['width_documented']=False
    if kind=='reference':plan['interfaces']['direction_reference']='testbench'
    assert compare(plan,rtl)['status']=='BLOCKED'


def test_alias_and_configuration_decision_is_explicit_and_snapshot_bound():
    plan,rtl=sample();rtl['ports'][0]['name']='bus_data';plan['interfaces']['signals'][0]['width']='8 or 32'
    assert compare(plan,rtl)['status']=='BLOCKED'
    d=decision(plan,rtl,mappings={'DATA_I':'bus_data'},width_choices={'DATA_I':8})
    assert compare(plan,rtl,d)['status']=='PASS'
    rtl['parameters']=[dict(name='WIDTH',width=32)]
    assert compare(plan,rtl,d)['status']=='BLOCKED'


def test_conditional_missing_requires_review_and_extra_rtl_cannot_be_hidden():
    plan,rtl=sample();plan['interfaces']['signals'].append(dict(name='DEBUG_O',width='1',direction='output',availability='DEBUG_ENABLE'))
    assert compare(plan,rtl)['status']=='BLOCKED'
    d=decision(plan,rtl,inactive_spec_ports={'DEBUG_O':'DEBUG_ENABLE is off'})
    assert compare(plan,rtl,d)['status']=='PASS'
    plan['interfaces']['signals'][-1]['documented']={'availability':False}
    d=decision(plan,rtl,inactive_spec_ports={'DEBUG_O':'DEBUG_ENABLE is off'})
    assert compare(plan,rtl,d)['status']=='BLOCKED'
    del plan['interfaces']['signals'][-1]['documented']
    rtl['ports'].append(dict(name='DEBUG_O',width=1,direction='output'))
    d=decision(plan,rtl,inactive_spec_ports={'DEBUG_O':'DEBUG_ENABLE is off'})
    assert compare(plan,rtl,d)['status']=='BLOCKED'


def test_malformed_review_fields_remain_blocked():
    plan,rtl=sample()
    d=decision(plan,rtl,mappings=['DATA_I'])
    assert compare(plan,rtl,d)['status']=='BLOCKED'


def test_gate_blocks_before_model_or_sv_even_with_explicit_contract(inputs):
    from dv_agent.codegen import build_project
    root,plan,rtl,contract,source=inputs
    plan['interfaces']['signals'][0]['width']=99
    (root/'plan.json').write_text(json.dumps(plan))
    with pytest.raises(ValueError,match='port comparison BLOCKED'):
        build_project(root/'plan.json',root/'interface.json',root/'output',contract_path=root/'contract.json',rtl_files=[source])
    assert json.loads((root/'output/interface_port_comparison.json').read_text())['status']=='BLOCKED'
    assert not list((root/'output').rglob('*.sv'))
    assert not list((root/'output').rglob('*.svh'))
