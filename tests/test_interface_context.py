import copy
import json

from dv_agent.codegen.interface_context import scoped, source_ids
from dv_agent.codegen.port_comparison import compare, enforce
from dv_agent.codegen.workplan import Evidence
from test_codegen import inputs, workflow_model


def grouped(plan):
    plan=copy.deepcopy(plan)
    signals=plan['interfaces']['signals'][2:]
    quote='Acknowledge completes a transfer'
    evidence=dict(provenance='DOCUMENTED',quote=quote,cited_chunk_ids=['CH-spec'])
    plan['interfaces']['groups'].append(dict(name='Control bus',protocol='WISHBONE',dut_role='responder',
        peer_type='interconnect',connected_to='system',signals=signals,
        property_evidence=dict(protocol=evidence,dut_role=dict(evidence,provenance='INFERRED',inference_reason='Proposed role'))))
    for s in signals: s.update(description='Register transfer port',quote=quote,chunk_id='CH-spec')
    return plan


def test_context_preserves_provenance_and_scope_and_deduplicates_quotes(inputs):
    _,plan,definition,_,_=inputs
    plan=grouped(plan)
    report=compare(plan,definition)
    context=scoped(report,['ready','push'])
    assert {p['rtl_name'] for p in context['ports']}=={'ready','push'}
    assert {p['testbench_responsibility'] for p in context['ports']}=={'drive','observe'}
    group=context['groups'][0]
    assert group['properties']['protocol']=='WISHBONE'
    assert group['properties']['peer_type']=='interconnect'
    assert group['property_evidence']['dut_role']['provenance']=='INFERRED'
    assert len(context['source_quotes'])==1
    assert source_ids(context)=={'CH-spec'}
    assert report['relationship_context']['ports'][2]['specification']['quote']=='Acknowledge completes a transfer'
    definition['ports'][2]['width']=999
    assert scoped(compare(plan,definition),['index'])=={}


def test_pinned_group_evidence_survives_unrelated_retrieval(inputs):
    _,plan,_,_,_=inputs
    plan=grouped(plan)
    evidence=Evidence(plan,{'CH-spec':plan['evidence_index']['CH-spec']['excerpt']})
    context=evidence.fetch(['no lexical matches'],plan_pointers=['/interfaces/groups/2'],item_limit=2)
    assert context['documented_items']
    assert all(i['plan_pointer'].startswith('/interfaces/groups/2/') for i in context['documented_items'])


def test_quote_hints_require_actual_source_and_retain_offsets():
    source='noise '*500+'Required port declaration.'+' tail '*500
    evidence=Evidence({}, {'spec':source})
    result=evidence.fetch(['noise'],quote_hints=[('spec','fabricated quote'),('spec','Required port declaration.')])
    window=result['source_excerpts'][0]
    assert window['text']=='Required port declaration.'
    assert source[window['start']:window['end']]==window['text']


def test_interface_stages_receive_shared_relation_and_saved_context(inputs):
    from dv_agent.codegen import build_project
    root,plan,definition,contract,source=inputs
    plan=grouped(plan)
    (root/'plan.json').write_text(json.dumps(plan))
    llm=workflow_model(contract)
    build_project(root/'plan.json',root/'interface.json',root/'output',llm=llm,rtl_files=[source],compile=False)
    for stage,payload in llm.calls:
        if stage not in ('code_interfaces','code_interface_base','code_interface_needs','code_interface'): continue
        relation=payload['spec_rtl_relation']
        assert relation['groups'][0]['properties']['protocol']=='WISHBONE'
        assert not {'tick','clear'} & {p['rtl_name'] for p in relation['ports']}
        assert any(i['plan_pointer'].startswith('/interfaces/groups/2/') for i in payload['evidence']['documented_items'])
    saved=list((root/'output/code_work').glob('*/interface_control.context.json'))
    assert saved and json.loads(saved[0].read_text())['spec_rtl_relation']['ports']


def test_markdown_includes_source_context(inputs):
    root,plan,definition,_,_=inputs
    enforce(grouped(plan),definition,root)
    text=(root/'interface_port_comparison.md').read_text()
    assert 'Control bus' in text and 'Acknowledge completes a transfer' in text
