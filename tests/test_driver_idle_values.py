import json
import pytest

from test_codegen import inputs,workflow_model,build
from test_quick_testing_rounds import quick_run
from dv_agent.codegen.contracts import CodePlan
from dv_agent.codegen.validate import validate


def test_idle_setting_uses_agent_driver_without_permanent_tie(inputs):
    root,plan,definition,contract,_=inputs
    contract['agents'][0]['idle_values']={'writing':0}
    (root/'contract.json').write_text(json.dumps(contract))
    result=build(inputs)
    from pathlib import Path
    driver=(Path(result['code_dir'])/'uvm/control_driver.svh').read_text()
    assert "cfg.vif.we = 64'h0;" in driver
    assert not result.get('tie_offs')


def test_generic_driver_and_monitor_templates_share_full_interface_and_reset_defaults():
    """The custom (hook-based) driver and monitor templates: defaults in one reset function, full signal access, monitor reads only."""
    from dv_agent.codegen.render import template
    driver = template('custom_driver.svh', AGENT='control', RESET_ASSIGNMENTS="    cfg.vif.writing = 64'h0;",
                      DRIVER_HOOK='      repeat (req.cycles) @(posedge cfg.vif.clk);')
    monitor = template('custom_monitor.svh', AGENT='control', MONITOR_SIGNAL_DECLARATIONS='  logic sampled_writing;',
                       MONITOR_RESET_ASSIGNMENTS="    sampled_writing = 1'b0;",
                       MONITOR_SIGNAL_ASSIGNMENTS='    sampled_writing = cfg.vif.writing;', MONITOR_HOOK='    // observe')
    assert 'virtual function void drive_reset_values()' in driver
    assert 'drive_reset_values();' in driver and 'virtual task drive_item(cg_item tr)' in driver
    reset = driver.split('virtual function void drive_reset_values()', 1)[1].split('endfunction', 1)[0]
    assert 'cfg.vif.writing =' in reset and 'cfg.vif.pull =' not in reset
    assert 'sampled_writing = cfg.vif.writing;' in monitor and 'virtual function void reset_values()' in monitor
    assert 'cfg.vif.pull =' not in monitor  # the monitor never drives DUT signals


@pytest.mark.parametrize('values',[{'pull':0},{'writing':2},{'missing':0}])
def test_idle_value_requires_owned_input_and_valid_width(inputs,values):
    _,spec,definition,contract,_=inputs
    contract['agents'][0]['idle_values']=values
    with pytest.raises(ValueError,match='Idle values must fit'):
        validate(CodePlan.model_validate(contract),spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']})


def test_previous_tieoff_approval_gets_replacement_idle_review(inputs,monkeypatch):
    from dv_agent.codegen import build_project
    from dv_agent.core.llm import FakeLLM
    from dv_agent.quality.human_review import ReviewClient,review_handler,request_review
    from dv_agent.plan.approved_clarifications import apply_approval
    root,plan,definition,contract,rtl=inputs
    run,path=quick_run(root,plan,monkeypatch)
    seen=[]
    def evaluate(payload):
        seen.append(payload['allowed_fields'])
        bindings={'tie_offs':{'writing':0}} if 'tie_offs' in payload['allowed_fields'] else {'idle_values':{'writing':0}}
        return dict(bindings_json=json.dumps(bindings),reason='Test-only input setting',reply='Set the input idle low.',assumptions=['Test only'])
    with review_handler(ReviewClient(llm=FakeLLM({'quick_testing_auto_approval':evaluate}),show=lambda _:None)):
        request,receipt=request_review(run,json.loads(path.read_text()),definition,'collateral_control',['Old idle question'],{})
        apply_approval(path,request,receipt)
        result=build_project(path,root/'interface.json',run,llm=workflow_model(contract),rtl_files=[rtl],compile=False)
    assert result['status']=='BUILT_NEEDS_REVIEW'
    assert len(seen)==2 and 'tie_offs' not in seen[1] and 'idle_values' in seen[1]
    doc=json.loads(path.read_text())
    assert doc['quick_test_approvals'][-1]['bindings']=={'idle_values':{'writing':0}}
