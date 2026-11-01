"""Demo testbench: a simulation that runs, with no DUT behaviour checked.

For a quick demo the testbench only has to compile, apply reset, drive and run. This builds a contract with no
model call from facts that already exist: the interface JSON, the plan's interface groups and the spec/RTL port
comparison. It is deliberately minimal:

- clock and reset use the common UVCs (bound by `common_binding`; when that still needs an owner decision,
  a name hint is used and recorded as a question);
- every other interface becomes one agent with a generic driver that holds its DUT inputs at zero, and a
  passive monitor; there are no scoreboards, registers, routes, checks or coverage;
- one test runs the idle sequences for a fixed number of cycles.

Nothing here claims the DUT is correct. The contract is marked `demo`, every question says so, and the output
stays NEEDS_REVIEW.
"""
import json
import re
from pathlib import Path

from ..plan.interface_roles import INFRASTRUCTURE, group_role
from .common_binding import _group_fact, _norm, resolve
from .contracts import Fact, identifier, is_identifier, safe_identifier

DEMO_IDLE_CYCLES = 64
DEMO_NOTE = "Demo testbench: connectivity and a running simulation only; no DUT behaviour is checked."


def _ports(definition):
    ports = {}
    for p in definition["ports"]:
        p = dict(p)
        if "width" not in p:
            match = re.fullmatch(r"\[(\d+):\s*(\d+)\]", p.get("range", ""))
            if not match:
                raise ValueError("Code generation needs resolved port widths")
            p["width"] = abs(int(match[1]) - int(match[2])) + 1
        ports[p["name"]] = p
    return ports


def _spec_to_rtl(directory):
    """Reviewed spec-name to RTL-port pairs from the port comparison, when a run has one."""
    path = Path(directory) / "interface_port_comparison.json"
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    from .port_validation import validated
    if not validated(report): return {}
    return {r["spec"]: r["rtl"] for r in report['rows'] if isinstance(r, dict) and r.get("status") == "PASS" and r.get("spec") and r.get("rtl")}


def _any_documented_fact(plan, sources):
    """Fallback citation: the first cited DOCUMENTED plan item, quoting the first line of its source."""
    from .reasoning import eligible_items
    for item in eligible_items(plan, sources):
        sid = item["source_ids"][0]
        quote = next((line.strip()[:160] for line in sources.get(sid, "").splitlines() if len(line.strip()) >= 8), "")
        if quote:
            return Fact(id="demo_basis", statement="Cited specification item", source_id=sid, quote=quote,
                        plan_pointer=item["plan_pointer"])
    return None


def _hinted(options, tokens, taken=()):
    found = [n for n in options if n not in taken and any(t in _norm(n) for t in tokens)]
    return found[0] if len(found) == 1 else None


def _bind_clock_reset(definition, plan, sources, top, ports, mapping):
    """Clock, reset and reset level. A decision or documented fact wins; otherwise a name hint, recorded."""
    questions = []
    try:
        result = resolve(definition, plan, sources, top=top)
    except ValueError:
        result = None
    if result and not result["questions"]:
        return result["clock"].clock, result["reset"].reset, result["reset"].reset_active, questions
    scalar = sorted(n for n, p in ports.items() if p["direction"] == "input" and p["width"] == 1)
    groups = [g for g in (plan.get("interfaces") or {}).get("groups", []) if group_role(g) == INFRASTRUCTURE]

    def pick(category, tokens, taken=()):
        for g in groups:
            if g.get("category") == category and len(g["signals"]) == 1 and mapping.get(g["signals"][0]["name"]) in scalar:
                return mapping[g["signals"][0]["name"]]
        return _hinted(scalar, tokens, taken)
    clock = pick("clock", ("clk", "clock"))
    reset = pick("reset", ("rst", "reset"), taken={clock})
    if not clock or not reset:
        raise ValueError("Demo needs one clock and one reset input; none could be identified from the reviewed port mapping or names")
    levels = [s["active_level"] for g in groups if g.get("category") == "reset" for s in g["signals"]
              if s.get("active_level_documented") and s.get("active_level") in ("high", "low")]
    level = levels[0] if len(levels) == 1 else ("low" if re.search(r"(?:^|_)n(?:$|_)|n$|_l$|b$", reset.lower()) else "high")
    if len(levels) != 1:
        questions.append(f"Demo only: reset {reset} level assumed {level} from its name; confirm the active level.")
    questions.append(f"Demo only: clock {clock} and reset {reset} were chosen from the port mapping or names; confirm the binding.")
    return clock, reset, level, questions


def _groups(plan, ports, taken, mapping):
    """Remaining DUT ports grouped by the plan's interface groups; leftovers share one 'misc' group."""
    remaining = {n for n in ports if n not in taken}
    out, claimed = [], set()
    by_norm = {_norm(n): n for n in remaining}
    for g in (plan.get("interfaces") or {}).get("groups", []):
        if group_role(g) == INFRASTRUCTURE and g.get("category") in ("clock", "reset"):
            continue
        names = []
        for s in g.get("signals", []):
            rtl = mapping.get(s["name"]) or by_norm.get(_norm(s["name"]))
            if rtl in remaining and rtl not in claimed:
                names.append(rtl)
                claimed.add(rtl)
        if names:
            out.append((g["name"], names))
    leftover = sorted(remaining - claimed)
    if leftover:
        out.append(("misc", leftover))
    return sorted(out, key=lambda group: (len(group[1]), sum(ports[n]["width"] for n in group[1])))  # fewest wires first


def _split(groups, ports, limit):
    """The first `limit` groups (smallest first) are built; the rest are deferred. A prototype needs one that drives the DUT."""
    if not limit or limit >= len(groups):
        return list(groups), []
    built, deferred = list(groups[:limit]), list(groups[limit:])
    drives = lambda group: any(ports[n]["direction"] == "input" for n in group[1])
    while deferred and not any(drives(g) for g in built):
        nxt = next((g for g in deferred if drives(g)), None)
        if nxt is None:
            break
        deferred.remove(nxt)
        built.append(nxt)
    return built, deferred


def build_demo_contract(plan, definition, sources, *, top=None, directory=".", limit=None, pending=None):
    """Return the demo contract as a dict (validated later by the normal CodePlan checks).

    limit: build only this many interfaces, fewest wires first. The others are deferred: their inputs are held at 0 in the
    testbench top, their outputs are left open, and each is appended to `pending` (and to the contract's questions).
    """
    ports = _ports(definition)
    mapping = _spec_to_rtl(directory)
    top = top or (re.sub(r"\.[A-Za-z]+$", "", definition["sources"][0]) if len(definition.get("sources") or []) == 1 else None)
    if not top:
        raise ValueError("The top module is not known: pass the selected top")
    fact = next((f for i, g in enumerate((plan.get("interfaces") or {}).get("groups", []))
                 if (f := _group_fact(plan, i, g, "demo_basis", "The specification defines this interface"))), None)
    if fact is None:
        fact = _any_documented_fact(plan, sources)
    if fact is None:
        raise ValueError("The plan has no documented, cited item to attach to a demo")
    clock, reset, level, questions = _bind_clock_reset(definition, plan, sources, top, ports, mapping)
    agents, hooks, sequences, tie_offs = [], [], [], []
    built, deferred = _split(_groups(plan, ports, {clock, reset}, mapping), ports, limit)
    for name, names in deferred:
        inputs = [n for n in names if ports[n]["direction"] == "input"]
        tie_offs += [dict(id=safe_identifier("defer_" + n).lower(), signal=n, value=0, fact_ids=[fact.id]) for n in inputs]
        if pending is not None:
            pending.append(dict(interface=name, ports=list(names), inputs_held_at_zero=inputs,
                                outputs_left_open=[n for n in names if n not in inputs]))
    for name, names in built:
        base = safe_identifier(name)
        agent_id = ("demo_" + base).lower()
        while not is_identifier(agent_id) or agent_id.endswith("_control"):
            agent_id += "_x"
        bindings = {(n if n not in ("clk", "reset") else "p_" + n): n for n in names}
        inputs = [role for role, n in bindings.items() if ports[n]["direction"] == "input"]
        active = bool(inputs)
        agents.append(dict(id=agent_id, protocol="custom", bindings=bindings, fact_ids=[fact.id], active=active, coverage_enabled=False))
        hooks.append(dict(id=agent_id + "_monitor_hook", target=agent_id, slot="monitor.body",
                          purpose="Demo: nothing is sampled", fact_ids=[fact.id]))
        if active:
            hooks.append(dict(id=agent_id + "_driver_hook", target=agent_id, slot="driver.body",
                              purpose="Demo: wait; drive_reset_values holds the inputs at their defaults", fact_ids=[fact.id]))
            sequences.append(dict(id=agent_id + "_idle", agent=agent_id, purpose="Idle", fact_ids=[fact.id],
                                  operations=[dict(kind="idle", cycles=DEMO_IDLE_CYCLES)]))
    if not sequences:
        raise ValueError("The demo needs at least one DUT input interface to drive")
    questions += [DEMO_NOTE]
    if deferred:
        questions.append("PENDING, not built in this prototype: " + "; ".join(f"{n} ({len(p)} ports)" for n, p in deferred) +
                         ". Their inputs are held at 0 and their outputs are left open. Run /code again to build them.")
    return dict(contract="verification_codegen_v1", top=top, clock=clock, reset=reset, reset_active=level,
                facts=[fact.model_dump()], agents=agents, hooks=hooks, sequences=sequences, tie_offs=tie_offs,
                tests=[dict(id="demo_smoke", stages=[[s["id"] for s in sequences]], drain_cycles=DEMO_IDLE_CYCLES,
                            minimum_comparisons=0, fact_ids=[fact.id])],
                questions=questions, demo=True)


def demo_hook_code(plan, ports):
    """Fixed hook bodies for a demo contract: wait while idle, sample nothing.

    The driver template's drive_reset_values() already holds every owned input at its default, so the hook only waits.
    """
    return {hook.id: "      repeat (req.cycles) @(posedge cfg.vif.clk);" if hook.slot == "driver.body" else "      // demo: connectivity only"
            for hook in plan.hooks}
