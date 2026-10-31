"""Synthetic designs exercise the generic alignment contract, without baseline repositories."""
import pytest

from dv_agent.codegen.interface_context import scoped
from dv_agent.codegen.port_comparison import compare
from dv_agent.quality.human_review import sha


def review(plan,rtl,**choices):
    return dict(spec_hash=sha(plan['interfaces']),rtl_hash=sha(rtl),reviewer='Integration engineer',
                reason='Reviewed this configured design and source inventory',**choices)


@pytest.mark.parametrize('protocol,ports',[
    ('pixel_stream',[('pixel_payload',30,'input'),('frame_marker',1,'input'),('space_available',1,'output')]),
    ('memory_link',[('memory_address',48,'input'),('memory_data',128,'inout'),('memory_ready',1,'output')]),
    ('sensor_events',[('sample_event',1,'input'),('measurement',96,'output'),('alarm_event',1,'output')]),
    ('project_defined_protocol',[('operand_vector',257,'input'),('result_vector',513,'output')])])
def test_protocol_and_design_names_are_data(protocol,ports):
    signals=[dict(name=n.upper(),width=w,direction=d,chunk_id='source_design') for n,w,d in ports]
    plan=dict(interfaces=dict(status='PASS',signals=signals,groups=[dict(name='Selected interface',protocol=protocol,signals=signals)]))
    rtl=dict(sources=['selected_design.sv'],direction_reference='DUT',parameters=[],
             ports=[dict(name=n,width=w,direction=d) for n,w,d in ports])
    report=compare(plan,rtl)
    assert report['status']==report['independent_validation']['status']=='PASS'
    context=scoped(report,[n for n,_,_ in ports])
    assert context['groups'][0]['properties']['protocol']==protocol
    assert {p['rtl_name'] for p in context['ports']}=={n for n,_,_ in ports}
    if any(d=='inout' for _,_,d in ports):
        assert next(p for p in context['ports'] if p['dut_direction']=='inout')['testbench_responsibility']=='bidirectional_ownership_required'


@pytest.mark.parametrize('options',['12 or 24 or 48','12/24/48','12, 24, or 48','12,24,48',[12,24,48]])
def test_arbitrary_finite_width_choices_are_independently_validated(options):
    plan=dict(interfaces=dict(status='PASS',signals=[dict(name='PAYLOAD',width=options,direction='input')]))
    rtl=dict(ports=[dict(name='payload',width=24,direction='input')])
    assert compare(plan,rtl)['status']=='BLOCKED'
    decision=review(plan,rtl,width_choices={'PAYLOAD':24})
    assert compare(plan,rtl,decision)['status']=='PASS'
    assert compare(plan,rtl,review(plan,rtl,width_choices={'PAYLOAD':32}))['status']=='BLOCKED'


@pytest.mark.parametrize('options',['12,,24','12 or','0/24/48',[True,24,48],'SIZE_A or SIZE_B'])
def test_unsupported_width_choices_are_not_guessed(options):
    plan=dict(interfaces=dict(status='PASS',signals=[dict(name='PAYLOAD',width=options,direction='input')]))
    rtl=dict(ports=[dict(name='payload',width=24,direction='input')])
    assert compare(plan,rtl,review(plan,rtl,width_choices={'PAYLOAD':24}))['status']=='BLOCKED'


def test_large_inventory_uses_indexed_matching_in_both_implementations(monkeypatch):
    from dv_agent.codegen import port_validation
    count=512
    signals=[dict(name=f'CHANNEL_{i}_PAYLOAD',width=(i%16+1)*11,direction='input' if i%2 else 'output') for i in range(count)]
    groups=[dict(name=f'Group {j}',protocol='user_defined',signals=signals[j:j+32]) for j in range(0,count,32)]
    plan=dict(interfaces=dict(status='PASS',signals=signals,groups=groups))
    rtl=dict(sources=['array_fabric.sv'],ports=[dict(s,name=s['name'].lower()) for s in signals])
    calls=0
    original=port_validation._name
    def counted(value):
        nonlocal calls
        calls+=1
        return original(value)
    monkeypatch.setattr(port_validation,'_name',counted)
    report=compare(plan,rtl)
    assert report['status']=='PASS'
    assert calls==count*2
    context=scoped(report,[s['name'].lower() for s in signals[:8]])
    assert len(context['ports'])==8 and len(context['groups'])==1


def test_normalized_collisions_remain_ambiguous():
    plan=dict(interfaces=dict(status='PASS',signals=[dict(name='LINE_DATA',width=23,direction='input')]))
    rtl=dict(ports=[dict(name=n,width=23,direction='input') for n in ['line_data','linedata']])
    assert compare(plan,rtl)['status']=='BLOCKED'


def test_independent_auditor_rejects_faulty_finite_choice_parser(monkeypatch):
    plan=dict(interfaces=dict(status='PASS',signals=[dict(name='PAYLOAD',width=[12,24,48],direction='input')]))
    rtl=dict(ports=[dict(name='payload',width=99,direction='input')])
    decision=review(plan,rtl,width_choices={'PAYLOAD':99})
    monkeypatch.setattr('dv_agent.codegen.port_comparison.width_options',lambda value:{99})
    assert compare(plan,rtl,decision,validate=False)['status']=='PASS'
    assert compare(plan,rtl,decision)['status']=='BLOCKED'
