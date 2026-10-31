import json
import pytest

from dv_agent.quality.quick_testing import ENV,prepare_run,test_item_allowed as allowed
from dv_agent.codegen.reasoning import eligible_items
from dv_agent.codegen.validate import validate_facts
from dv_agent.codegen.contracts import Fact
from test_human_review import seed


def source(tmp_path):
    run,plan,definition=seed(tmp_path)
    quote='Payload remains stable until acceptance.'
    item=dict(text='Check payload stability',kind='check',provenance='INFERRED',
              inference_reason='Recommended check for the documented transfer constraint',
              cited_chunk_ids=['CH-transfer'],cited_req_ids=[],details=[],validation=[])
    plan['sections'][0]['entries']=[item]
    plan['evidence_index']={'CH-transfer':dict(excerpt=quote,path='spec.md')}
    (run/'dv/testplan_doc.json').write_text(json.dumps(plan))
    return run,quote


def test_inferred_content_approved_only_in_isolated_copy_and_mode(tmp_path,monkeypatch):
    original,quote=source(tmp_path);before=(original/'dv/testplan_doc.json').read_text()
    monkeypatch.setenv(ENV,'1');out=prepare_run(original)
    path=out/'dv/testplan_doc.json';plan=json.loads(path.read_text());item=plan['sections'][0]['entries'][0]
    assert item['provenance']=='INFERRED' and item['review_status']=='TEST_AUTO_APPROVED'
    assert item['inference_reason'] and item['cited_chunk_ids']==['CH-transfer']
    assert plan['sections'][0]['review_status']=='TEST_AUTO_APPROVED'
    assert allowed(plan,item)
    sources={'CH-transfer':quote}
    assert any(i['plan_pointer']=='/sections/0/entries/0' for i in eligible_items(plan,sources))
    fact=Fact(id='stability',statement=item['text'],quote=quote,source_id='CH-transfer',plan_pointer='/sections/0/entries/0')
    validate_facts([fact],plan,sources)
    assert (original/'dv/testplan_doc.json').read_text()==before
    snapshot=path.read_text();assert prepare_run(out)==out and path.read_text()==snapshot
    for suffix in ('md','html'): assert 'TEST_AUTO_APPROVED' in path.with_suffix('.'+suffix).read_text()
    monkeypatch.setenv(ENV,'0')
    assert not allowed(plan,item)
    with pytest.raises(ValueError,match='not a documented'): validate_facts([fact],plan,sources)
    with pytest.raises(ValueError,match='explicit quick-testing switch'): prepare_run(original)


def test_edit_invalidates_approval_and_missing_quote_still_fails(tmp_path,monkeypatch):
    run,quote=source(tmp_path);monkeypatch.setenv(ENV,'1');out=prepare_run(run)
    plan=json.loads((out/'dv/testplan_doc.json').read_text())
    fact=Fact(id='bad',statement='Test',quote='Invented source statement',source_id='CH-transfer',plan_pointer='/sections/0/entries/0')
    with pytest.raises(ValueError,match='quote does not match'): validate_facts([fact],plan,{'CH-transfer':quote})
    item=plan['sections'][0]['entries'][0];item['text']='Changed behavior'
    assert not allowed(plan,item)
