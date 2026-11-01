"""Quick testing only: defer a feature's unsupported checks, coverage goals and scoreboard hooks.

Checks and coverage goals that name an agent which does not exist,
and scoreboard hooks that have no route to compare, are dropped.

Such output usually describes the clock or reset, which are common UVCs and not agents. The rest of the feature is
kept; each dropped item is removed, the pseudocode steps that mapped to it become explicit questions, and the drop is
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
    if not dropped:
        return {}
    for mapping in fragment.step_implementations:
        mapping.component_ids = [c for c in mapping.component_ids if c not in dropped]
        if not mapping.component_ids and not mapping.question.strip():
            mapping.question = "Deferred: " + "; ".join(dropped.values())
    fragment.questions.extend("Deferred (quick testing): " + reason for reason in dropped.values())
    return dropped
