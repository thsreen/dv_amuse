"""A decision the model got right is kept; a fact it could not prove is replaced, never trusted."""
import json
from pathlib import Path

import pytest

from dv_agent.codegen.contracts import Agent, Fact
from dv_agent.codegen.fact_reconcile import reconcile_facts
from dv_agent.codegen.units import InfrastructureNeeds, InterfaceUnit
from test_codegen import inputs, workflow_model  # noqa: F401  (fixture and helper)


def fact(identifier, quote="a verbatim quote"):
    return Fact(id=identifier, statement="s", source_id="CH-1", quote=quote, plan_pointer="/x")


def proven(allowed):
    def check(f):
        if f.id not in allowed:
            raise ValueError("Fact quote must occur in a retrieved source excerpt")
    return check


def unit_with(facts, agent_facts):
    agent = Agent(id="bus", protocol="custom", bindings={"a": "a"}, fact_ids=agent_facts)
    return InterfaceUnit(agents=[agent], facts=facts)


def test_unprovable_facts_are_dropped_and_references_follow_the_proven_ones():
    unit = unit_with([fact("good"), fact("bad")], ["bad", "good"])
    assert reconcile_facts(unit, proven({"good"})) == ["bad"]
    assert [f.id for f in unit.facts] == ["good"] and unit.agents[0].fact_ids == ["good"]
    assert any("Evidence substituted: bad" in q and "Review the choice" in q for q in unit.questions)


def test_a_reference_that_only_cited_unprovable_facts_falls_back_to_the_interfaces_own_facts():
    unit = unit_with([fact("bad")], ["bad"])
    base = [fact("port_a")]
    reconcile_facts(unit, proven(set()), fallback=base)
    assert [f.id for f in unit.facts] == ["port_a"] and unit.agents[0].fact_ids == ["port_a"]  # nothing unproven survives


def test_nothing_provable_and_no_fallback_is_still_refused():
    unit = unit_with([fact("bad")], ["bad"])
    with pytest.raises(ValueError, match="No cited fact can be proven"):
        reconcile_facts(unit, proven(set()))


def test_a_fully_proven_answer_is_untouched():
    unit = unit_with([fact("good")], ["good"])
    assert reconcile_facts(unit, proven({"good"})) == [] and unit.questions == []


BOGUS = dict(id='made_up', statement='x', source_id='CH-spec', quote='This sentence is not in the source text',
             plan_pointer='/sections/0/entries/0')


def test_normal_mode_does_not_substitute_evidence(inputs,monkeypatch):
    from dv_agent.codegen.workplan import design
    root,spec,definition,contract,_=inputs
    monkeypatch.setenv('DV_AGENT_QUICK_TEST_AUTO_APPROVE','0')
    llm=workflow_model(contract)
    normal=llm.handlers['code_interface_needs']
    llm.handlers['code_interface_needs']=lambda p:dict(normal(p),facts=[BOGUS])
    with pytest.raises(ValueError,match='Fact quote'): design(llm,spec,definition,{'CH-spec':spec['evidence_index']['CH-spec']['excerpt']},root/'output')


def test_needs_assessment_with_an_unprovable_fact_keeps_the_decision_and_the_run_continues(inputs, monkeypatch):
    from dv_agent.codegen.workplan import design
    root, spec, definition, contract, _ = inputs
    monkeypatch.setenv('DV_AGENT_QUICK_TEST_AUTO_APPROVE','1')
    spec['test_only']=True
    (root/'output').mkdir(exist_ok=True)
    (root/'output/quick_testing.json').write_text('{}')
    llm = workflow_model(contract)
    normal = llm.handlers['code_interface_needs']
    llm.handlers['code_interface_needs'] = lambda p: dict(normal(p), facts=[BOGUS])
    plan = design(llm, spec, definition, {'CH-spec': spec['evidence_index']['CH-spec']['excerpt']}, root / 'output')
    assert [a.id for a in plan.agents] == ['control']  # the model's choice (a full agent) survived
    assert any('Evidence substituted: made_up' in q for q in plan.questions)
    work = Path(json.loads((root / 'output/code_work_manifest.json').read_text())['work_dir'])
    decision = json.loads((work / 'infrastructure_needs/control.json').read_text())
    assert decision['level'] == 'full_agent' and [f['id'] for f in decision['facts']] != ['made_up']


def test_collateral_that_cites_an_unprovable_fact_is_repointed_not_blocked(inputs, monkeypatch):
    from dv_agent.codegen.workplan import design
    root, spec, definition, contract, _ = inputs
    monkeypatch.setenv('DV_AGENT_QUICK_TEST_AUTO_APPROVE','1')
    spec['test_only']=True
    (root/'output').mkdir(exist_ok=True)
    (root/'output/quick_testing.json').write_text('{}')
    llm = workflow_model(contract)
    normal = llm.handlers['code_interface']

    def collateral(payload):
        result = normal(payload)
        result['facts'] = result['facts'] + [BOGUS]
        result['agents'][0]['fact_ids'] = ['made_up']
        return result
    llm.handlers['code_interface'] = collateral
    plan = design(llm, spec, definition, {'CH-spec': spec['evidence_index']['CH-spec']['excerpt']}, root / 'output')
    agent = next(a for a in plan.agents if a.id == 'control')
    assert 'made_up' not in agent.fact_ids and agent.fact_ids  # points at proven facts
    assert 'made_up' not in {f.id for f in plan.facts}
    assert any('Evidence substituted: made_up' in q for q in plan.questions)


def test_a_port_scoped_fetch_reaches_every_signal_of_a_group_with_many_properties():
    """The failure: 8 property items pinned first and filled all 8 slots, so none of the signal evidence was shown."""
    from dv_agent.codegen.units import PORT_SCOPED_ITEM_LIMIT
    from dv_agent.codegen.workplan import Evidence
    text = "\n".join(f"SIG{i} 1 Input Signal number {i}" for i in range(8)) + "\nBlock overview"
    evidence = lambda quote: dict(provenance="DOCUMENTED", cited_chunk_ids=["CH-1"], quote=quote, inference_reason="")
    group = dict(name="bus", category="bus", cited_chunk_ids=["CH-1"],
                 property_evidence={k: evidence("Block overview") for k in
                                    ("name", "function", "category", "protocol", "connected_to", "peer_type", "dut_role", "is_sideband")},
                 signals=[dict(name=f"SIG{i}", direction="input", provenance="DOCUMENTED", chunk_id="CH-1",
                               quote=f"SIG{i} 1 Input Signal number {i}") for i in range(8)])
    plan = dict(interfaces=dict(status="PASS", groups=[group]), sections=[])
    ev = Evidence(plan, {"CH-1": text})
    pinned = ["/interfaces/groups/0"]
    old = ev.fetch(["bus signals"], item_limit=8, focus=True, plan_pointers=pinned)
    assert not any("/signals/" in i["plan_pointer"] for i in old["documented_items"])  # what the run saw
    new = ev.fetch(["bus signals"], item_limit=PORT_SCOPED_ITEM_LIMIT, focus=True, plan_pointers=pinned)
    assert sum("/signals/" in i["plan_pointer"] for i in new["documented_items"]) == 8


def test_an_agent_named_after_the_unit_is_renamed_to_the_interface_id_with_its_references(inputs):
    """The model is shown the unit id (collateral_<interface>) and often uses it as the agent id; the script owns that id."""
    from dv_agent.codegen.workplan import design
    root, spec, definition, contract, _ = inputs
    llm = workflow_model(contract)
    normal = llm.handlers['code_interface']

    def collateral(payload):
        result = normal(payload)
        unit = payload['task_id']
        result['agents'] = [dict(result['agents'][0], id=unit)]  # copies: the fixture's contract is shared
        result['registers'] = [dict(r, agent=unit) for r in result['registers']]
        return result
    llm.handlers['code_interface'] = collateral
    plan = design(llm, spec, definition, {'CH-spec': spec['evidence_index']['CH-spec']['excerpt']}, root / 'output')
    assert [a.id for a in plan.agents] == ['control']
    assert all(r.agent == 'control' for r in plan.registers)


def test_a_different_fact_under_an_id_another_unit_used_is_renamed_with_its_references(inputs):
    """Run …0513…: the collateral unit's `f_int_o_source` differed from an earlier unit's, and the run stopped."""
    from dv_agent.codegen.fact_reconcile import rename_conflicting_facts
    from dv_agent.codegen.units import InterfaceUnit
    root, spec, definition, contract, _ = inputs
    mine = dict(contract['facts'][0], id='f_source')
    other = dict(mine, statement='A different statement of the same label', id='f_source')
    unit = InterfaceUnit.model_validate(dict(
        agents=[dict(id='control', protocol='custom', bindings={'x': 'tick'}, fact_ids=['f_source'])],
        facts=[mine], tie_offs=[dict(id='t', signal='clear', value=0, fact_ids=['f_source'])]))
    renamed = rename_conflicting_facts(unit, {'f_source': other})
    assert renamed == {'f_source': 'f_source_2'} and [f.id for f in unit.facts] == ['f_source_2']
    assert unit.agents[0].fact_ids == ['f_source_2'] and unit.tie_offs[0].fact_ids == ['f_source_2']
    again = InterfaceUnit.model_validate(dict(facts=[mine]))
    assert rename_conflicting_facts(again, {'f_source': dict(mine)}) == {}  # an identical fact merges, it is not renamed
    assert rename_conflicting_facts(again, {}) == {}
