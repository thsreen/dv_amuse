"""Interface base: ports and their cited evidence, bound without a model."""
import json
from types import SimpleNamespace

import pytest

from dv_agent.codegen.interface_base import interface_base
from dv_agent.codegen.validate import validate_facts

TEXT = "WB_ADDR_I 5 Input Used for register selection\nWB_DAT_O 32 Output Data output\nBlock overview text."


def plan_with(signals, **extra):
    group = dict(name="bus", category="bus", signals=signals, property_evidence={})
    return dict(interfaces=dict(status="PASS", groups=[group]), sections=[], evidence_index={"CH-1": dict(excerpt=TEXT)}, **extra)


def signal(name, quote, **kw):
    return dict(name=name, direction="input", quote=quote, chunk_id="CH-1", provenance="DOCUMENTED", **kw)


SOURCES = {"CH-1": TEXT}
TASK = SimpleNamespace(id="bus", signals=["wb_adr_i", "wb_dat_o"])


def test_each_port_is_cited_from_its_own_signal_evidence(tmp_path,monkeypatch):
    monkeypatch.setattr("dv_agent.codegen.interface_base._spec_to_rtl",lambda directory:{"WB_ADDR_I":"wb_adr_i","WB_DAT_O":"wb_dat_o"})
    plan = plan_with([signal("WB_ADDR_I", "WB_ADDR_I 5 Input Used for register selection"),
                      signal("WB_DAT_O", "WB_DAT_O 32 Output Data output")])
    (tmp_path / "interface_port_comparison.json").write_text(json.dumps(dict(rows=[
        dict(spec="WB_ADDR_I", rtl="wb_adr_i", status="PASS"), dict(spec="WB_DAT_O", rtl="wb_dat_o", status="PASS")])))
    base = interface_base(plan, TASK, SOURCES, tmp_path)
    assert base.ports == ["wb_adr_i", "wb_dat_o"] and base.roles == {} and base.questions == []
    assert [(f.id, f.plan_pointer) for f in base.facts] == [("port_wb_adr_i", "/interfaces/groups/0/signals/0"),
                                                            ("port_wb_dat_o", "/interfaces/groups/0/signals/1")]
    validate_facts(base.facts, plan, SOURCES)  # the same proof gate the model's facts failed


def test_no_fact_can_quote_text_the_model_was_never_shown(tmp_path):
    """The failure this replaces: context facts (a heading, a protocol line) outside the retrieved excerpts."""
    plan = plan_with([signal("WB_ADDR_I", "WB_ADDR_I 5 Input Used for register selection")])
    base = interface_base(plan, SimpleNamespace(id="bus", signals=["wb_adr_i"]), SOURCES, tmp_path)
    for fact in base.facts:
        assert fact.quote in TEXT  # every quote is a verbatim line of the cited source


def test_unmapped_ports_fall_back_to_the_group_then_to_any_documented_item(tmp_path):
    plan = plan_with([signal("OTHER", "nothing matching these ports here")])
    group_fact = interface_base(plan, SimpleNamespace(id="bus", signals=["wb_adr_i"]), SOURCES, tmp_path).facts
    assert [f.id for f in group_fact] != ["port_wb_adr_i"]  # no signal maps, so it cites something else documented
    plan["sections"] = [dict(id="s", entries=[dict(provenance="DOCUMENTED", cited_chunk_ids=["CH-1"], text="x")])]
    plan["interfaces"]["groups"] = []
    assert interface_base(plan, SimpleNamespace(id="zzz", signals=["wb_adr_i"]), SOURCES, tmp_path).facts[0].id == "interface_basis"


def test_a_port_list_with_duplicates_or_nothing_is_refused(tmp_path):
    plan = plan_with([signal("WB_ADDR_I", "WB_ADDR_I 5 Input Used for register selection")])
    for ports in ([], ["wb_adr_i", "wb_adr_i"]):
        with pytest.raises(ValueError, match="exactly once"):
            interface_base(plan, SimpleNamespace(id="bus", signals=ports), SOURCES, tmp_path)


def test_more_than_sixteen_ports_are_capped_not_refused(tmp_path):
    names = [f"p{i}" for i in range(20)]
    lines = "\n".join(f"{n.upper()} 1 Input Port number {i}" for i, n in enumerate(names))
    plan = plan_with([signal(n.upper(), f"{n.upper()} 1 Input Port number {i}") for i, n in enumerate(names)])
    plan["evidence_index"]["CH-1"]["excerpt"] = lines
    base = interface_base(plan, SimpleNamespace(id="bus", signals=names), {"CH-1": lines}, tmp_path)
    assert len(base.ports) == 20 and len(base.facts) == 16
