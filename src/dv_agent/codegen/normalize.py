"""Names and shapes the script owns, applied to every model answer in the code stage before it is judged.

A model chooses what an interface or feature does. It does not own agent ids, protocol role names, fact-id uniqueness or
the byte-select wiring of a narrow bus: those follow from the ports and the templates, and refusing an answer over them
cost repair attempts and stopped runs while the decision itself was fine. Everything changed that a reviewer should see
is written into the unit's questions. Nothing here adds behaviour or evidence.
"""
from .contracts import Agent, TieOff, safe_identifier
from .fact_reconcile import rename_conflicting_facts, reuse_existing_facts
from .validate import agent_id_is_free, builtin_protocol, canonical_roles

BODY_SLOTS = ("driver.body", "monitor.body")
UNIT_PREFIXES = ("collateral_", "interface_", "assessment_")


def safe_interface_ids(interfaces):
    """An interface id becomes its agent id, so it must not collide with the environment. The script renames it here,
    before any unit uses it; a repair could not fix it later because the agent id always follows the interface id."""
    taken = {task.id for task in interfaces}
    for task in interfaces:
        if agent_id_is_free(task.id):
            continue
        name = task.id + "_if"
        while name in taken or not agent_id_is_free(name):
            name += "_x"
        taken.add(name)
        task.id = name


def _fill_missing_agent(unit, task, ports, level):
    """The assessment asked for an agent and the answer has none: its ports and cited facts are enough to declare it."""
    if level not in ("full_agent", "passive_agent") or unit.agents or unit.tie_offs or not unit.facts:
        return
    if any(name not in ports for name in task.signals):
        return
    active = level == "full_agent" and any(ports[name]["direction"] == "input" for name in task.signals)
    unit.agents.append(Agent(id=task.id, protocol="custom", bindings={("p_" + n if n in ("clk", "reset") else n): n for n in task.signals},
                             fact_ids=[f.id for f in unit.facts], active=active, coverage_enabled=False))
    unit.questions.append(f"Agent {task.id} was declared from its ports because the answer returned none; review its role.")


def _settle_protocol(unit, agent, ports):
    agent.bindings = canonical_roles(agent.protocol, agent.bindings, ports)
    if agent.protocol == "custom":
        protocol, roles = builtin_protocol(agent.bindings, ports)
        if protocol:
            agent.protocol, agent.bindings = protocol, roles
            unit.questions.append(f"Agent {agent.id} uses the built-in {protocol} protocol: its ports fill every {protocol} role, "
                                  "so its driver and monitor are template-owned.")


def _rename_agent(unit, task):
    """The agent id is the interface id: the model is shown the unit id (collateral_<interface>) and commonly uses that."""
    if len(unit.agents) != 1 or unit.agents[0].id == task.id:
        return
    old, unit.agents[0].id = unit.agents[0].id, task.id
    for item in (*unit.hooks, *unit.registers):
        for field in ("target", "agent"):
            if getattr(item, field, None) == old:
                setattr(item, field, task.id)


def _tie_unused_byte_select(unit, agent, ports):
    """A narrow bus configuration keeps its byte-select port but ignores it, so it is held at 0 and not driven as a lane select."""
    if agent.protocol != "wishbone" or "sel" not in agent.bindings or "wdata" not in agent.bindings:
        return
    select, data = agent.bindings["sel"], agent.bindings["wdata"]
    if select not in ports or data not in ports or ports[data]["width"] != 8 or ports[select]["width"] == 1:
        return
    del agent.bindings["sel"]
    agent.idle_values.pop(select, None)
    unit.tie_offs.append(TieOff(id=safe_identifier("hold_" + select).lower(), signal=select, value=0, fact_ids=list(agent.fact_ids)))
    unit.questions.append(f"{select} is held at 0: the {ports[data]['width']}-bit data bus configuration does not use byte lanes.")


def normalize_interface_unit(unit, task, ports, level):
    _fill_missing_agent(unit, task, ports, level)
    for agent in unit.agents:
        _settle_protocol(unit, agent, ports)
        _tie_unused_byte_select(unit, agent, ports)
    _rename_agent(unit, task)
    for agent in unit.agents:
        if agent.protocol != "custom":  # built-in protocols own their driver and monitor bodies
            unit.hooks[:] = [h for h in unit.hooks if not (h.target == agent.id and h.slot in BODY_SLOTS)]


def agent_alias(name, agent_ids):
    """The agent a model meant by a unit-style name (collateral_x, x_agent). Only an exact match after stripping counts, so
    an invented agent such as a clock agent is never mapped onto a real one."""
    if name in agent_ids:
        return name
    stripped = name
    for prefix in UNIT_PREFIXES:
        stripped = stripped.removeprefix(prefix)
    stripped = stripped.removesuffix("_agent")
    return stripped if stripped in agent_ids else name


def normalize_fragment(fragment, agent_ids, known_facts):
    """Feature answers: agent names resolve to the real agents, facts already in the plan are reused, and a fact id already
    used for different evidence gets a new id."""
    ids = set(agent_ids)
    for item in (*fragment.sequences, *fragment.checks, *fragment.coverage, *fragment.registers, *fragment.sequencer_variables):
        item.agent = agent_alias(item.agent, ids)
    for route in fragment.routes:
        route.expected_agent, route.actual_agent = agent_alias(route.expected_agent, ids), agent_alias(route.actual_agent, ids)
        for condition in route.when:
            condition.agent = agent_alias(condition.agent, ids)
    for hook in fragment.hooks:
        hook.target = agent_alias(hook.target, ids)
    reuse_existing_facts(fragment, known_facts)
    return rename_conflicting_facts(fragment, known_facts)
