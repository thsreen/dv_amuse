"""Quick testing only: defer a feature's unsupported checks, coverage goals and scoreboard hooks.

Checks, coverage goals and sequences that name an agent which does not exist, scoreboard hooks with no route, and any other
item that keeps the contract from validating are dropped. The rest of the feature is kept; each dropped item is removed, the pseudocode steps that mapped to it become explicit questions, and the drop is
written into the feature's questions so a reviewer sees what was not built. Nothing is invented to replace it.
"""


def defer_unknown_agents(fragment, agent_ids, route_ids=None, *, bus_ids=None):
    """Drop checks, coverage goals and sequences whose agent is not in agent_ids, built-in checks on an agent that is not a bus
    (given bus_ids), and scoreboard hooks with no route (given route_ids). Returns {dropped item id: reason}.
    """
    known = set(agent_ids)
    dropped = {}
    if bus_ids is not None:
        for check in list(fragment.checks):
            if check.agent in known and check.agent not in bus_ids:
                dropped[check.id] = f"check {check.id} is a built-in bus check on {check.agent}, which is not a bus agent"
                fragment.checks.remove(check)
    for kind, items in (("check", fragment.checks), ("coverage goal", fragment.coverage), ("sequence", fragment.sequences)):
        for item in list(items):
            if item.agent not in known:
                dropped[item.id] = f"{kind} {item.id} named agent {item.agent}, which does not exist (clock and reset are common UVCs, not agents)"
                items.remove(item)
    if route_ids is not None:
        routes = set(route_ids)
        for hook in list(fragment.hooks):
            if hook.slot == "scoreboard.compare" and hook.target not in routes:
                dropped[hook.id] = (f"scoreboard hook {hook.id} targets {hook.target}, which is not a declared route "
                                    "(comparisons need two observed interface events; internal state is not observable here)")
                fragment.hooks.remove(hook)
    return _record(fragment, dropped)


def _record(fragment, dropped):
    """Steps that mapped to a dropped item become explicit questions, and the drop is written into the feature's questions."""
    if not dropped:
        return {}
    for mapping in fragment.step_implementations:
        mapping.component_ids = [c for c in mapping.component_ids if c not in dropped]
        if not mapping.component_ids and not mapping.question.strip():
            mapping.question = "Deferred: " + "; ".join(reason for item, reason in dropped.items())
    fragment.questions.extend("Deferred (quick testing): " + reason for reason in dropped.values())
    return dropped


# What an item depends on comes first, so a dependency is in place when its dependents are tried.
COMPONENTS = ("registers", "sequencer_variables", "sequences", "routes", "checks", "coverage", "hooks")


def defer_until_valid(fragment, check):
    """Keep the items that fit the contract and drop the rest, whatever rule they break, recording the rule.

    check(fragment) raises ValueError while the fragment does not fit. Starting from no items, each is added in dependency
    order and kept only if the contract still validates; items refused are tried again once others are in place, for
    dependencies inside the answer. Building up finds the fault item by item: removing items one at a time cannot, because
    several items often break the same rule. If the contract does not validate even without the items, nothing is dropped
    and the normal check reports it. Returns {dropped item id: reason}.
    """
    try:
        check(fragment)
        return {}
    except ValueError:
        pass
    kept = fragment.model_copy(deep=True)
    for key in COMPONENTS:
        getattr(kept, key).clear()
    try:
        check(kept)
    except ValueError:
        return {}
    pending = [(key, item) for key in COMPONENTS for item in getattr(fragment, key)]
    errors, progress = {}, True
    while pending and progress:
        progress, refused = False, []
        for key, item in pending:
            getattr(kept, key).append(item)
            try:
                check(kept)
                progress = True
            except ValueError as exc:
                getattr(kept, key).pop()
                errors[item.id] = str(exc).splitlines()[0][:240]
                refused.append((key, item))
        pending = refused
    for key in COMPONENTS:
        getattr(fragment, key)[:] = getattr(kept, key)
    return _record(fragment, {item.id: f"{key.rstrip('s')} {item.id} does not fit the testbench: {errors[item.id]}" for key, item in pending})


# A prototype feature passes with deferrals once this many of its items are complete (user decision, quick testing).
MIN_COMPLETE_ITEMS = 2
COUNTED = ("sequences", "routes", "checks", "coverage", "hooks")


def complete_items(fragment):
    return sum(len(getattr(fragment, key)) for key in COUNTED)


def feature_status(deferred, complete):
    """PASS unless items were deferred and too few are left; DEFERRED features do not stop the run."""
    return "DEFERRED" if deferred and complete < MIN_COMPLETE_ITEMS else "PASS"
