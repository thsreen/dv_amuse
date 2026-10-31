"""Clock and reset binding for the common UVC environment: small fixed steps, no model."""
import json

import pytest

from dv_agent.codegen.common_binding import STEPS, resolve

QUOTE = "CLK 1 Input Block clock input"


def definition(*extra, sources=("dut_top.v",)):
    ports = [dict(name="CLK", direction="input", width=1), dict(name="rst_n", direction="input", width=1),
             dict(name="data", direction="input", width=8), dict(name="irq", direction="output", width=1)]
    return dict(sources=list(sources), direction_reference="DUT", parameters=[], ports=ports + list(extra))


def group(name, category, signal, *, level=("unknown", False), direction="input"):
    evidence = dict(provenance="DOCUMENTED", cited_chunk_ids=["CH-1"], quote=QUOTE, inference_reason="")
    return dict(name=name, category=category, function="Testbench " + name, cited_chunk_ids=["CH-1"],
                property_evidence=dict(function=evidence),
                signals=[dict(name=signal, direction=direction, active_level=level[0], active_level_documented=level[1],
                              quote=QUOTE, chunk_id="CH-1")])


def plan(*groups, **extra):
    return dict(interfaces=dict(status="PASS", groups=list(groups)), sections=[], **extra)


SOURCES = {"CH-1": QUOTE + " and reset"}


def test_exact_name_match_binds_clock_and_documented_reset_level_without_questions():
    p = plan(group("timebase", "clock", "clk"), group("init", "reset", "RST_N", level=("low", True)))
    result = resolve(definition(), p, SOURCES)
    assert result["questions"] == []
    clock, reset = result["clock"], result["reset"]
    assert (clock.top, clock.clock, clock.clock_period_ns, clock.clock_period_ranges) == ("dut_top", "CLK", 10, [])
    assert (reset.reset, reset.reset_active, reset.reset_cycles) == ("rst_n", "low", 8)
    assert clock.facts[0].plan_pointer == "/interfaces/groups/0/property_evidence/function" and clock.facts[0].source_id == "CH-1"
    assert [s["id"] for s in result["steps"]] == ["inventory", "clock", "reset", "timing"] and [s[0] for s in STEPS][:4] == ["inventory", "clock", "reset", "timing"]


def test_a_name_that_matches_nothing_asks_one_precise_question_instead_of_guessing():
    p = plan(group("timebase", "clock", "SYSCLK"), group("init", "reset", "RST_N", level=("high", True)))
    result = resolve(definition(), p, SOURCES)
    assert result["clock"] is None and [q["unit"] for q in result["questions"]] == ["foundation_clock"]
    question = result["questions"][0]
    assert question["kind"] == "port_binding" and "SYSCLK" in question["text"]
    assert "CLK, rst_n" in question["text"] and "data" not in question["text"] and "irq" not in question["text"]  # scalar inputs only
    assert question["excerpts"][0]["text"] == QUOTE


def test_reviewed_comparison_alias_binds_without_repeat_question():
    p = plan(group('timebase', 'clock', 'SYSCLK'), group('init', 'reset', 'RST_N', level=('high', True)))
    result = resolve(definition(), p, SOURCES, port_mapping={'SYSCLK': 'CLK'})
    assert result['questions'] == []
    assert result['clock'].clock == 'CLK'


def test_missing_polarity_and_missing_groups_each_become_a_question():
    undocumented = resolve(definition(), plan(group("timebase", "clock", "CLK"), group("init", "reset", "rst_n")), SOURCES)
    assert [(q["unit"], q["kind"]) for q in undocumented["questions"]] == [("foundation_reset", "reset_polarity")]
    assert "asserted high (1) or low (0)" in undocumented["questions"][0]["text"] and "rst_n" in undocumented["questions"][0]["text"]
    none = resolve(definition(), plan(), SOURCES)
    assert [q["unit"] for q in none["questions"]] == ["foundation_clock", "foundation_reset"]
    several = resolve(definition(), plan(group("a", "clock", "CLK"), group("b", "clock", "CLK2"), group("r", "reset", "rst_n", level=("high", True))), SOURCES)
    assert [q["unit"] for q in several["questions"]] == ["foundation_clock"] and "several clock signals" in several["questions"][0]["text"]


def test_derived_outputs_and_non_scalar_ports_are_never_candidates():
    outputs_only = plan(group("tick", "clock", "irq", direction="output"), group("init", "reset", "rst_n", level=("high", True)))
    assert resolve(definition(), outputs_only, SOURCES)["questions"][0]["text"].startswith("The plan has no testbench-supplied clock")
    wide = plan(group("timebase", "clock", "data"), group("init", "reset", "rst_n", level=("high", True)))
    assert "no port name matches" in resolve(definition(), wide, SOURCES)["questions"][0]["text"]


def approval(unit, bindings, *, test=False):
    rid = "r1"
    sid = ("QUICK-TEST-" if test else "HUMAN-") + rid
    return sid, dict(unit=unit, request_id=rid, source_id=sid, bindings=bindings, test_only=test, reason="designer said so")


def with_decision(p, unit, bindings, *, test=False):
    sid, record = approval(unit, bindings, test=test)
    p["sections"].append(dict(id="human_clarifications", entries=[dict(id=sid, text="approved")]))
    p["quick_test_approvals" if test else "human_approvals"] = [record]
    return sid


def test_an_owner_decision_is_final_and_cited_and_never_asked_again():
    p = plan(group("timebase", "clock", "SYSCLK"), group("init", "reset", "rst_n"))
    sources = dict(SOURCES)
    sid = with_decision(p, "foundation_clock", {"clock": "CLK", "clock_period_ns": 20})
    sources[sid] = "Human-approved infrastructure binding for foundation_clock: clock CLK"
    first = resolve(definition(), p, sources)
    assert [q["unit"] for q in first["questions"]] == ["foundation_reset"]  # only the reset level is still open
    reset_sid = "HUMAN-r2"
    p["sections"].append(dict(id="human_clarifications", entries=[dict(id=reset_sid, text="approved reset")]))
    p["human_approvals"].append(dict(unit="foundation_reset", request_id="r2", source_id=reset_sid, bindings={"reset_active": "high", "reset_cycles": 4},
                                     test_only=False, reason="x"))
    sources[reset_sid] = "Human-approved infrastructure binding for foundation_reset: reset_active high"
    done = resolve(definition(), p, sources)
    assert done["questions"] == []
    assert (done["clock"].clock, done["clock"].clock_period_ns) == ("CLK", 20)
    assert (done["reset"].reset, done["reset"].reset_active, done["reset"].reset_cycles) == ("rst_n", "high", 4)
    assert any(f.source_id == sid and f.id == "human_r1" for f in done["clock"].facts)
    assert any(f.source_id == reset_sid for f in done["reset"].facts)


def test_quick_test_decisions_are_marked_and_approved_bands_become_ranges():
    p = plan(group("timebase", "clock", "SYSCLK"), group("init", "reset", "rst_n", level=("high", True)))
    sid = with_decision(p, "foundation_clock", {"clock": "CLK", "clock_period_ranges": [dict(name="main", min_ps=5000, max_ps=40000, nominal_ps=10000)]}, test=True)
    result = resolve(definition(), p, dict(SOURCES, **{sid: "QUICK TEST ONLY: clock CLK"}))
    clock = result["clock"]
    assert [(r.name, r.min_ps, r.max_ps, r.provenance) for r in clock.clock_period_ranges] == [("main", 5000, 40000, "INFERRED")]
    assert clock.facts[-1].id == "test_r1" and clock.facts[-1].statement.startswith("Quick-testing inferred")


def test_the_top_comes_from_the_caller_or_the_single_interface_source():
    p = plan(group("timebase", "clock", "CLK"), group("init", "reset", "rst_n", level=("high", True)))
    assert resolve(definition(), p, SOURCES, top="chip")["clock"].top == "chip"
    with pytest.raises(ValueError, match="top module is not known"):
        resolve(definition(sources=("a.v", "b.v")), p, SOURCES)


def test_a_binding_without_cited_evidence_is_refused():
    p = plan(group("timebase", "clock", "CLK"), group("init", "reset", "rst_n", level=("high", True)))
    p["interfaces"]["groups"][0]["property_evidence"] = {}
    with pytest.raises(ValueError, match="need a cited fact"):
        resolve(definition(), p, SOURCES)


def test_binding_payloads_do_not_grow_with_the_plan():
    """The old model-driven unit sent retrieved evidence that grew every round. The question carries one quote."""
    big = plan(group("timebase", "clock", "SYSCLK"), group("init", "reset", "rst_n"))
    big["sections"] = [dict(id="s%d" % i, entries=[dict(id="e%d" % i, text="x" * 5000)]) for i in range(40)]
    result = resolve(definition(), big, SOURCES)
    assert len(json.dumps(result["questions"])) < 2000
