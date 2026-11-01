import json
from dv_agent.codegen.demo_contract import _spec_to_rtl
from dv_agent.codegen.port_comparison import compare


def test_unvalidated_and_changed_mapping_reports_are_not_consumed(tmp_path):
    path=tmp_path/'interface_port_comparison.json'
    path.write_text(json.dumps({'rows':[{'spec':'A','rtl':'b','status':'PASS'}]}))
    assert _spec_to_rtl(tmp_path)=={}
    plan={'interfaces':{'status':'PASS','signals':[{'name':'DATA','width':7,'direction':'input'}]}}
    definition={'ports':[{'name':'data','width':7,'direction':'input'}]}
    report=compare(plan,definition)
    path.write_text(json.dumps(report))
    assert _spec_to_rtl(tmp_path)=={'DATA':'data'}
    report['rows'][0]['rtl']='different_port'
    path.write_text(json.dumps(report))
    assert _spec_to_rtl(tmp_path)=={}
