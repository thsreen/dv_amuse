"""UART acceptance data only. Production generator/templates remain design-agnostic."""
import json
import re
from pathlib import Path

from pypdf import PdfReader


def create(directory):
    from rtl_agent.extractor import extract_interface
    from rtl_agent.builder import interface_definition
    repo=Path(__file__).resolve().parents[2]/'baseline_repos/uart16550'
    if not (repo/'doc/UART_spec.pdf').is_file():
        raise FileNotFoundError('UART baseline specification unavailable')
    directory.mkdir(parents=True,exist_ok=True)
    text=' '.join(' '.join(page.extract_text().split()) for page in PdfReader(repo/'doc/UART_spec.pdf').pages)
    integration=json.loads((Path(__file__).parent/'fixtures/codegen/uart_integration.json').read_text())
    snippets=[integration['statement']]
    for anchor,length in [('Name Address Width Access Description',1400),('4.5 Line Control Register (LCR)',1900),
                          ('4.9 Divisor Latches',1100),('0 R Data Ready (DR)',350),('5.1 Initialization',1000)]:
        start=text.index(anchor)
        snippets.append(text[start:start+length])
    sources={'integration':dict(path='explicit test integration configuration',excerpt=integration['statement'])}
    entries=[]; facts=[]
    for i,quote in enumerate(snippets):
        cid='integration' if i==0 else 'spec_'+str(i)
        if i: sources[cid]=dict(path='doc/UART_spec.pdf',excerpt=text)
        entries.append(dict(text=quote,provenance='DOCUMENTED',cited_chunk_ids=[cid]))
        facts.append(dict(id='fact_'+str(i),statement=quote,source_id=cid,quote=quote,plan_pointer='/sections/0/entries/'+str(i)))
    evidence=['fact_'+str(i) for i in range(len(facts))]
    binding={'addr':'wb_adr_i','wdata':'wb_dat_i','rdata':'wb_dat_o','we':'wb_we_i','stb':'wb_stb_i','cyc':'wb_cyc_i','ack':'wb_ack_o'}
    def operation(kind,address=0,data=0,**kwargs): return dict(kind=kind,address=address,data=data,**kwargs)
    def sequence(name,agent,ops): return dict(id=name,agent=agent,purpose=name,operations=ops,fact_ids=evidence)
    initialization=[operation('write',3,131),operation('write',1,0),operation('write',0,2),
                    operation('write',3,3),operation('write',1,0),operation('write',2,6)]
    contract=dict(top='uart_top',clock=integration['clock'],reset=integration['reset'],reset_active=integration['reset_active'],
        defines=integration['defines'],facts=facts,
        agents=[dict(id='register_bus',protocol='wishbone',bindings=binding,fact_ids=evidence),
                dict(id='serial_link',protocol='serial',bindings={'rx':'srx_pad_i','tx':'stx_pad_o'},
                     bit_cycles=32,data_bits=8,parity='none',stop_bits=1,fact_ids=evidence)],
        tie_offs=[dict(id='tie_'+name,signal=name,value=0,fact_ids=['fact_0']) for name in integration['tie_offs']],
        registers=[dict(id='line_control',agent='register_bus',address=3,width=8,access='RW',reset=3,mask=255,fact_ids=evidence)],
        sequences=[sequence('initialize_link','register_bus',initialization),
                   sequence('transmit_directed','register_bus',[operation('write',0,165)]),
                   sequence('receive_directed','serial_link',[operation('send',data=90)]),
                   sequence('read_received','register_bus',[operation('poll',5,1,mask=1),operation('read',0)]),
                   sequence('check_configuration','register_bus',[operation('read',3)]),
                   sequence('transmit_random','register_bus',[
                       op for _ in range(4) for op in (operation('poll',5,32,mask=32),operation('random_write',0,mask=255))])],
        routes=[dict(id='transmit_path',expected_agent='register_bus',expected_event='write',expected_address=0,
                     actual_agent='serial_link',actual_event='tx',mask=255,fact_ids=evidence),
                dict(id='receive_path',expected_agent='serial_link',expected_event='rx',
                     actual_agent='register_bus',actual_event='read',actual_address=0,mask=255,fact_ids=evidence)],
        checks=[dict(id='bus_known',agent='register_bus',kind='known_controls',fact_ids=evidence)],
        tests=[dict(id='basic_functional',stages=[['initialize_link'],['check_configuration'],['transmit_directed'],
                                                ['receive_directed'],['read_received']],drain_cycles=2048,minimum_comparisons=3,fact_ids=evidence),
               dict(id='random_transmit',stages=[['initialize_link'],['transmit_random']],drain_cycles=4096,minimum_comparisons=4,seed=7,fact_ids=evidence)],
        questions=['Banked register mirrors, FIFO side effects, interrupt priorities, loopback and error injection need additional supported contracts; they are not implemented by these acceptance tests.'])
    # Divisor setup aliases address zero: payload-route activation must not include initialization.
    # This fixture needs route qualification by observed configuration, never by driver intent.
    for route in contract['routes']:
        route['when']=[dict(agent='register_bus',address=3,mask=128,value=0,initial_value=3)]
    definition=interface_definition(extract_interface([repo/'rtl/verilog/uart_top.v'],'uart_top',defines={'DATA_BUS_WIDTH_8':'1'}))
    # Parse the independent specification table, not the RTL port list.
    table=text[text.index('2 IO ports'):text.index('3 Clocks')]
    signals=[dict(name=m[1],width=m[2],direction=m[3].lower(),chunk_id='spec_ports',width_documented=True,
                  direction_documented=True,availability='UART_HAS_BAUDRATE_OUTPUT' if m[1]=='BAUD_O' else '')
             for m in re.finditer(r'\b([A-Z][A-Z0-9_]+)\s+(\d+(?:\s+or\s+\d+)?)\s+(Input|Output)\b',table)]
    sources['spec_ports']=dict(path='doc/UART_spec.pdf',excerpt=table)
    specification=dict(source_authority='DOCUMENTED',interfaces=dict(status='PASS',signals=signals),sections=[dict(id='feature_description',entries=entries)],evidence_index=sources)
    from dv_agent.quality.human_review import sha
    output=directory/'output';output.mkdir(exist_ok=True)
    decisions=dict(spec_hash=sha(specification['interfaces']),rtl_hash=sha(definition),reviewer='Acceptance integration fixture',
                   reason='Explicit DATA_BUS_WIDTH_8 fixture wiring; original spec aliases and conditional baud output.',
                   mappings={'CLK':'wb_clk_i','WB_ADDR_I':'wb_adr_i'},width_choices={'WB_ADDR_I':3,'WB_DAT_I':8,'WB_DAT_O':8},
                   inactive_spec_ports={'BAUD_O':'UART_HAS_BAUDRATE_OUTPUT is not selected in this fixture'})
    (output/'interface_port_mapping.json').write_text(json.dumps(decisions))
    for name,value in [('testplan.json',specification),
                       ('interface.json',definition),('code_contract.json',contract)]:
        (directory/name).write_text(json.dumps(value,indent=2)+'\n')
    return repo
