"""Deterministic clock and reset binding for the common UVM environment.

The testbench supplies the clock and the reset. All that generated code needs from the plan is a correct
binding: which scalar DUT input is the clock, which is the reset, and the reset's active level. Everything
else comes from the reusable UVCs in `dv_agent/uvc/` (clock UVC, reset UVC, and the common agent and
environment that instantiate both).

Earlier this was two model-driven units per run. Each request carried retrieved evidence, repair feedback
and every earlier clarification, so it grew with each round; a model that kept asking for confirmation of an
answer it already had never converged, and the run ended with "work package too large". Here every step has
a small fixed input and the model is not involved:

1. inventory   scalar DUT inputs from the interface JSON, testbench-supplied clock/reset groups from the plan
2. clock       bind the clock port (exact name match, or one recorded owner decision)
3. reset       bind the reset port and its active level (documented, or one recorded owner decision)
4. timing      testbench period and reset duration (operational settings; bands only if approved)
5. render      copy the common UVC templates; the generated test instantiates common_env
6. validate    scalar inputs, clock differs from reset, facts are cited and exist in the plan

A missing decision becomes one precise question for the owner. Once answered, the answer is final: it is read
back from the plan, never re-asked.
"""
import re

from ..plan.interface_roles import INFRASTRUCTURE, group_role
from .contracts import Fact

DEFAULT_CLOCK_PERIOD_NS = 10  # testbench operational setting, not a DUT limit
DEFAULT_RESET_CYCLES = 8

STEPS = (
    ("inventory", "Collect scalar DUT inputs and the testbench-supplied clock/reset groups"),
    ("clock", "Bind the clock port"),
    ("reset", "Bind the reset port and its active level"),
    ("timing", "Set the testbench clock period and reset duration"),
    ("render", "Copy the common clock/reset UVCs and the common agent and environment"),
    ("validate", "Check the bindings against the port inventory"),
)


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _approvals(plan, unit):
    """Bindings the owner (or an isolated quick-testing run) already decided for this unit, newest last."""
    merged, source = {}, None
    for approval in list(plan.get("human_approvals", [])) + list(plan.get("quick_test_approvals", [])):
        if approval.get("unit") == unit:
            merged.update(approval.get("bindings", {}))
            source = approval
    return merged, source


def _sections_entry(plan, source_id):
    for si, section in enumerate(plan.get("sections", [])):
        for ei, entry in enumerate(section.get("entries") or []):
            if entry.get("id") == source_id:
                return f"/sections/{si}/entries/{ei}"
    return None


def _group_fact(plan, index, group, fact_id, statement):
    evidence_by_property = group.get("property_evidence") or {}
    # The category says what the group is; the function and name are documented descriptions of it.
    key = next((k for k in ("category", "function", "name")
                if (evidence_by_property.get(k) or {}).get("provenance") == "DOCUMENTED"), None)
    if key is None:
        return None
    evidence = evidence_by_property[key]
    ids = evidence.get("cited_chunk_ids") or group.get("cited_chunk_ids") or []
    quote = evidence.get("quote") or ""
    if not ids or len(quote) < 8:
        return None
    return Fact(id=fact_id, statement=statement, source_id=ids[0], quote=quote,
                plan_pointer=f"/interfaces/groups/{index}/property_evidence/{key}")


def _approval_fact(plan, sources, approval, fact_id):
    sid = approval.get("source_id") or "HUMAN-" + approval.get("request_id", "")
    pointer, quote = _sections_entry(plan, sid), (sources.get(sid) or "")[:1600]
    if not pointer or len(quote) < 8:
        return None
    return Fact(id=fact_id, statement=("Quick-testing inferred binding" if approval.get("test_only") else "Human-approved infrastructure binding"),
                source_id=sid, quote=quote, plan_pointer=pointer)


def _excerpt(group, signal=None):
    signal = signal or (group.get("signals") or [{}])[0]
    text = signal.get("quote") or ""
    return dict(source_id=signal.get("chunk_id", ""), start=0, end=len(text), text=text)


def resolve(definition, plan, sources, *, top=None, port_mapping=None):
    """Return clock/reset units when every binding is decided, else the questions that remain.

    {clock, reset, questions: [{unit, kind, text, excerpts}], steps: [...]}. Pure: no model, no file access.
    """
    from .units import ClockUnit, ResetUnit
    ports = {p["name"]: p for p in definition.get("ports", [])}
    for port in ports.values():
        if "width" not in port:
            match = re.fullmatch(r"\[(\d+):\s*(\d+)\]", port.get("range", ""))
            if not match:
                raise ValueError("Units require resolved port widths")
            port["width"] = abs(int(match[1]) - int(match[2])) + 1
    scalar_inputs = sorted(n for n, p in ports.items() if p["direction"] == "input" and p.get("width") == 1)
    groups = [(i, g) for i, g in enumerate((plan.get("interfaces") or {}).get("groups", [])) if group_role(g) == INFRASTRUCTURE]
    clock_groups = [(i, g) for i, g in groups if g.get("category") == "clock"]
    reset_groups = [(i, g) for i, g in groups if g.get("category") == "reset"]
    questions, facts = [], dict(clock=[], reset=[])
    steps = [dict(id="inventory", status="PASS", detail=f"{len(scalar_inputs)} scalar inputs, {len(clock_groups)} clock and {len(reset_groups)} reset group(s)")]

    def pick(unit, kind, groups_for_unit, bindings, key, taken=()):
        """One port for a clock or reset: owner decision, else an exact name match, else a question."""
        if bindings.get(key):
            return bindings[key]
        options = [n for n in scalar_inputs if n not in taken]
        if len(groups_for_unit) == 1 and len(groups_for_unit[0][1]["signals"]) == 1:
            index, group = groups_for_unit[0]
            signal = group["signals"][0]
            mapped=(port_mapping or {}).get(signal['name'])
            exact = [n for n in options if n==mapped] if mapped else [n for n in options if _norm(n) == _norm(signal["name"])]
            if len(exact) == 1:
                fact = _group_fact(plan, index, group, f"{kind}_binding",
                                   f"The specification defines {signal['name']} as the testbench-supplied {kind}")
                if fact:
                    facts[kind].append(fact)
                return exact[0]
            text = (f"Which DUT input is the {kind} named {signal['name']} in the specification ({group['name']})? "
                    f"The JSON ports are: {', '.join(options)}; no port name matches it exactly.")
            questions.append(dict(unit=unit, kind="port_binding", text=text, excerpts=[_excerpt(group, signal)]))
        elif not groups_for_unit:
            questions.append(dict(unit=unit, kind="port_binding", excerpts=[],
                                  text=f"The plan has no testbench-supplied {kind} group. Which DUT input is the {kind}? Candidates: {', '.join(options)}."))
        else:
            names = ", ".join(s["name"] for _, g in groups_for_unit for s in g["signals"])
            questions.append(dict(unit=unit, kind="port_binding", excerpts=[_excerpt(g) for _, g in groups_for_unit][:2],
                                  text=f"The plan defines several {kind} signals ({names}). Which DUT input is the {kind} to drive? Candidates: {', '.join(options)}."))
        return None

    clock_bindings, clock_approval = _approvals(plan, "foundation_clock")
    reset_bindings, reset_approval = _approvals(plan, "foundation_reset")
    clock = pick("foundation_clock", "clock", clock_groups, clock_bindings, "clock")
    reset = pick("foundation_reset", "reset", reset_groups, reset_bindings, "reset", taken={clock} if clock else ())
    steps += [dict(id="clock", status="PASS" if clock else "NEEDS_DECISION", detail=clock or "owner decision needed"),
              dict(id="reset", status="PASS" if reset else "NEEDS_DECISION", detail=reset or "owner decision needed")]

    active = reset_bindings.get("reset_active")
    if reset and not active:
        documented = [s for _, g in reset_groups for s in g["signals"] if s.get("active_level_documented") and s.get("active_level") in ("high", "low")]
        if len(documented) == 1:
            active = documented[0]["active_level"]
        else:
            name = reset or "the reset input"
            questions.append(dict(unit="foundation_reset", kind="reset_polarity",
                                  excerpts=[_excerpt(g) for _, g in reset_groups][:1],
                                  text=f"Is {name} asserted high (1) or low (0)? The specification text cited does not state it."))
    if not questions:
        for unit, approval, keys in (("clock", clock_approval, ("clock", "clock_period_ns", "clock_period_ranges")),
                                     ("reset", reset_approval, ("reset", "reset_active", "reset_cycles"))):
            if approval and any((approval.get("bindings") or {}).get(k) for k in keys):
                fact = _approval_fact(plan, sources, approval, ("test_" if approval.get("test_only") else "human_") + approval["request_id"])
                if fact:
                    facts[unit].append(fact)
    if questions:
        steps.append(dict(id="timing", status="WAITING", detail="after the open decisions"))
        return dict(clock=None, reset=None, questions=questions, steps=steps)

    ranges = []
    if clock_bindings.get("clock_period_ranges"):
        from .clock_timing import reviewed_ranges
        ranges = reviewed_ranges(clock_bindings["clock_period_ranges"],
                                 clock_approval.get("source_id", "HUMAN-" + clock_approval["request_id"]),
                                 test=clock_approval.get("test_only", False), reason=clock_approval.get("reason", ""))
    period = clock_bindings.get("clock_period_ns", DEFAULT_CLOCK_PERIOD_NS)
    cycles = reset_bindings.get("reset_cycles", DEFAULT_RESET_CYCLES)
    steps.append(dict(id="timing", status="PASS", detail=f"period {period} ns, reset {cycles} cycles, {len(ranges)} approved band(s)"))
    if not facts["clock"] or not facts["reset"]:
        raise ValueError("Clock and reset bindings need a cited fact: no interface evidence or recorded decision supports them")
    top = top or _top_from_sources(definition)
    clock_unit = ClockUnit(top=top, clock=clock, clock_period_ns=period, clock_period_ranges=ranges, facts=facts["clock"])
    reset_unit = ResetUnit(reset=reset, reset_active=active, reset_cycles=cycles, facts=facts["reset"])
    return dict(clock=clock_unit, reset=reset_unit, questions=[], steps=steps)


def _top_from_sources(definition):
    sources = definition.get("sources") or []
    if len(sources) == 1:
        return re.sub(r"\.[A-Za-z]+$", "", str(sources[0]))
    raise ValueError("The top module is not known: pass the selected top or give the interface JSON exactly one source")
