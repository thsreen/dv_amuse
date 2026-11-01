"""Deterministic evidence, topology, width and hook checks before SV rendering."""
import re

from ..ingest.extract import locate_quote
from .contracts import IDENTIFIER_RULE, identifier, is_identifier, pointer


ROLES = {
    "wishbone": {"addr": "input", "wdata": "input", "rdata": "output", "sel": "input",
                 "we": "input", "stb": "input", "cyc": "input", "ack": "output"},
    "serial": {"rx": "input", "tx": "output"},
}


# Words a model (or a port name) uses for each protocol role, compared without underscores.
ROLE_WORDS = {
    "addr": ("addr", "address", "adr"), "wdata": ("wdata", "writedata", "dati", "datain", "din"),
    "rdata": ("rdata", "readdata", "dato", "dataout", "dout"), "sel": ("sel", "select"),
    "we": ("we", "writeenable", "wren"), "stb": ("stb", "strobe"), "cyc": ("cyc", "cycle"), "ack": ("ack", "acknowledge"),
    "rx": ("rx", "rxd", "srx", "receive", "receiver", "received"), "tx": ("tx", "txd", "stx", "transmit", "transmitter", "transmitted"),
}


def canonical_roles(protocol, bindings, ports):
    """Rename an agent's binding keys to the protocol's role names when each maps unambiguously; else return it unchanged.

    The role names are owned by the protocol template, not by the model. A key (or, failing that, its port name) must
    match exactly one role of the right DUT direction, and every binding must land on a different role.
    """
    expected = ROLES.get(protocol)
    if not expected or set(bindings) <= set(expected) or any(name not in ports for name in bindings.values()):
        return bindings
    def hit(alias, text):
        tokens = [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]
        compact = "".join(tokens)
        return alias in tokens or (len(alias) >= 5 and alias in compact) or compact.endswith(alias)
    assigned = {}
    for key, name in bindings.items():
        roles = []
        for text in (key, name):
            roles = [r for r, direction in expected.items() if ports[name]["direction"] == direction
                     and r in ROLE_WORDS and any(hit(a, text) for a in ROLE_WORDS[r])]
            if roles: break
        if len(roles) != 1 or roles[0] in assigned: return bindings
        assigned[roles[0]] = name
    return assigned


def builtin_protocol(bindings, ports):
    """(protocol, roles) of the built-in protocol whose roles these bindings fill completely, else (None, bindings).

    A bus whose ports fill every bus role IS a bus, whatever the model called it: its driver and monitor are
    template-owned, and a `custom` agent would lose the built-in checks, register access and coverage.
    """
    for protocol, expected in ROLES.items():
        roles = canonical_roles(protocol, bindings, ports)
        required = set(expected) - ({"sel"} if protocol == "wishbone" else set())
        if (set(roles) <= set(expected) and required <= set(roles) and len(roles) == len(bindings)
                and all(ports[name]["direction"] == expected[role] for role, name in roles.items())):
            return protocol, roles
    return None, bindings


def validate(plan, specification, definition, sources):
    if specification.get("source_authority") == "RTL_INFERRED":
        raise ValueError("Unvalidated RTL-derived expectations cannot be compiled into verification code")
    identifier(plan.top)
    if abs(plan.clock_period_ns*1000-round(plan.clock_period_ns*1000))>1e-6:
        raise ValueError('Clock period must be representable at 1ps resolution')
    for define in plan.defines:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:=[A-Za-z0-9_']+)?", define):
            raise ValueError('Invalid explicit build define')
    ports = {p["name"]: p for p in definition["ports"]}
    if len(ports) != len(definition["ports"]):
        raise ValueError("Duplicate physical ports")
    for p in ports.values():
        identifier(p["name"])
        if "width" not in p:
            match = re.fullmatch(r"\[(\d+):(\d+)\]", p.get("range", ""))
            if not match:
                raise ValueError("Code generation needs resolved port widths")
            p = dict(p, width=abs(int(match[1]) - int(match[2])) + 1)
            ports[p["name"]] = p
        if not 1 <= p["width"] <= 64 or p["direction"] not in ("input", "output"):
            raise ValueError("Unsupported port shape: explicit 1..64-bit input/output required")
    if plan.clock == plan.reset:
        raise ValueError("Clock and reset must be distinct")
    for name in (plan.clock, plan.reset):
        if name not in ports or ports[name]["direction"] != "input" or ports[name]["width"] != 1:
            raise ValueError("Clock/reset binding must be an explicit scalar DUT input")
    for category in (plan.facts, plan.agents, plan.tie_offs, plan.registers, plan.sequences, plan.sequencer_variables, plan.routes, plan.checks, plan.tests, plan.hooks,plan.coverage):
        ids = [identifier(item.id) for item in category]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate code-plan IDs")
    facts = {f.id: f for f in plan.facts}
    validate_facts(plan.facts,specification,sources)
    from .clock_timing import validate_ranges
    from ..quality.quick_testing import enabled
    validate_ranges(plan.clock_period_ranges,plan.facts,test_only=enabled() and specification.get('test_only',False))
    for category in (plan.agents, plan.tie_offs, plan.registers, plan.sequences, plan.sequencer_variables, plan.routes, plan.checks, plan.tests, plan.hooks,plan.coverage):
        for item in category:
            if not set(item.fact_ids) <= facts.keys():
                raise ValueError(f"Unknown evidence for {item.id}")
    agents = {a.id: a for a in plan.agents}
    # A single package holds all generated classes, including generated drain/vseqs.
    symbols=['cg_item','cg_env','cg_scoreboard','cg_system_coverage']
    if plan.clock_period_ranges: symbols.append('cg_clock_coverage')
    symbols += [a.id+'_'+suffix for a in plan.agents for suffix in ('cfg','sequencer','driver','monitor','coverage','agent')]
    symbols += [s.id for s in plan.sequences] + [t.id for t in plan.tests]
    symbols += [t.id+'_vseq' for t in plan.tests]
    symbols += [t.id+'_'+a.id+'_drain' for t in plan.tests for a in plan.agents if a.active]
    symbols += [c.id+'_coverage' for c in plan.coverage]
    if len(symbols)!=len(set(symbols)):
        raise ValueError('Generated class names collide; choose distinct component/sequence/test IDs')
    if any(a.id in {'sb','system_cov','cmn_agent','cmn_cfg','build_phase','connect_phase','new'} or a.id.endswith('_control') for a in plan.agents):
        raise ValueError('Agent name collides with environment infrastructure')
    owners = {plan.clock: "clock_uvc", plan.reset: "reset_uvc"}
    for tie in plan.tie_offs:
        if (tie.signal not in ports or ports[tie.signal]["direction"] != "input" or tie.signal in owners
                or tie.value >= 1 << ports[tie.signal]["width"]):
            raise ValueError("Invalid or competing tie-off")
        owners[tie.signal] = tie.id
    for a in plan.agents:
        for name,value in a.idle_values.items():
            if (not a.active or name not in a.bindings.values() or name not in ports or ports[name]['direction']!='input'
                    or type(value) is not int or not 0<=value<1<<ports[name]['width']):
                raise ValueError('Idle values must fit active agent-owned DUT inputs')
            role=next(r for r,n in a.bindings.items() if n==name)
            if a.protocol=='serial' and (role!='rx' or value!=1):
                raise ValueError('Built-in serial driver supports only idle-high rx')
            if a.protocol=='wishbone' and role in ('cyc','stb','we') and value!=0:
                raise ValueError('Built-in bus controls must idle low')
        expected = ROLES.get(a.protocol)
        required = set(expected or {})
        if a.protocol=='wishbone' and 'sel' not in a.bindings and a.bindings.get('wdata') in ports and ports[a.bindings['wdata']]['width']==8:
            required.remove('sel')
        if expected and set(a.bindings) != required:
            raise ValueError(f"Agent {a.id} requires roles {sorted(expected)}")
        for role, name in a.bindings.items():
            identifier(role)
            if role in ('clk','reset'):
                raise ValueError('Protocol role collides with shared clock/reset')
            if name not in ports or name in (plan.clock, plan.reset):
                raise ValueError(f"Invalid signal binding {a.id}.{role}")
            p = ports[name]
            if expected and p["direction"] != expected[role]:
                raise ValueError(f"Wrong DUT direction for {a.id}.{role}")
            if p["direction"] == "input" and a.active:
                if name in owners:
                    raise ValueError(f"Competing drive ownership for {name}")
                owners[name] = a.id
        if a.protocol == "wishbone":
            if ports[a.bindings["wdata"]]["width"] != ports[a.bindings["rdata"]]["width"]:
                raise ValueError("Bus read/write widths differ")
            if 'sel' in a.bindings and ports[a.bindings["sel"]]["width"] * 8 != ports[a.bindings["wdata"]]["width"]:
                raise ValueError("Byte-select width does not match data width")
        scalar = ("rx", "tx") if a.protocol == "serial" else ("we", "stb", "cyc", "ack") if a.protocol == "wishbone" else ()
        if any(ports[a.bindings[r]]["width"] != 1 for r in scalar):
            raise ValueError("Protocol control/serial pins must be scalar")
    # Other DUT inputs must be explicitly bound; do not silently tie flow-control inputs.
    missing = {n for n, p in ports.items() if p["direction"] == "input"} - owners.keys()
    if missing:
        raise ValueError(f"Unbound DUT inputs require an explicit agent/binding: {sorted(missing)}")
    register_addresses = set()
    for r in plan.registers:
        if (r.agent, r.address) in register_addresses:
            raise ValueError("Banked/aliased register mirrors require an explicit extension")
        register_addresses.add((r.agent, r.address))
        if r.agent not in agents or agents[r.agent].protocol != "wishbone":
            raise ValueError("Register must reference a bus agent")
        if r.address >= 1 << ports[agents[r.agent].bindings["addr"]]["width"]:
            raise ValueError("Register address exceeds interface width")
        if r.mask >= 1 << r.width or r.reset is not None and not 0 <= r.reset < 1 << r.width:
            raise ValueError("Register reset/mask exceeds its width")
        if r.width > ports[agents[r.agent].bindings['rdata']]['width']:
            raise ValueError('Register exceeds bus data width')
    sequences = {s.id: s for s in plan.sequences}
    variables={v.id:v for v in plan.sequencer_variables}
    for var in variables.values():
        if var.agent not in agents or var.default>=1<<var.width or var.id in {'cfg','req','rsp','m_sequencer','p_sequencer'}:
            raise ValueError('Invalid sequencer variable owner, name or default width')
    for seq in plan.sequences:
        seen={seq.id};base=seq.extends
        while base:
            if base not in sequences or base in seen or sequences[base].agent!=seq.agent:
                raise ValueError('Sequence extension requires an acyclic base on the same agent')
            seen.add(base);base=sequences[base].extends
        bindings=set()
        for control in seq.controls:
            var=variables.get(control.variable)
            key=(control.operation,control.field)
            if key in bindings or control.operation>=len(seq.operations) or var is None or var.agent!=seq.agent:
                raise ValueError('Invalid p_sequencer control binding')
            bindings.add(key)
            op=seq.operations[control.operation]
            agent=agents.get(seq.agent)
            width=(ports[agent.bindings['addr']]['width'] if control.field=='address' and agent and agent.protocol=='wishbone' else
                   ports[agent.bindings['wdata']]['width'] if control.field=='data' and agent and agent.protocol=='wishbone' else
                   agent.data_bits if control.field=='data' and agent else 64)
            if var.width>width or control.field in ('count','cycles') and (var.width>10 or var.default<1):
                raise ValueError('Sequencer control exceeds operation width or bounded execution limits')
            if control.field=='data' and op.kind.startswith('random_'):
                raise ValueError('Random data and explicit sequencer data control conflict')
    for test in plan.tests:
        configured=set()
        for setting in test.sequencer_settings:
            var=variables.get(setting.variable)
            if (var is None or var.id in configured or setting.value>=1<<var.width
                    or not agents[var.agent].active):
                raise ValueError('Invalid per-test sequencer setting')
            configured.add(var.id)
            if setting.value==0 and any(b.variable==var.id and b.field in ('count','cycles')
                                       for seq in plan.sequences for b in seq.controls):
                raise ValueError('Sequencer execution count must be positive')
    for seq in plan.sequences:
        if seq.agent not in agents or not agents[seq.agent].active:
            raise ValueError("Sequence needs an active agent")
        agent = agents[seq.agent]
        for op in seq.operations:
            if op.kind == "idle":
                continue
            if op.kind == "register_write":
                register = next((r for r in plan.registers if r.id == op.register_id), None)
                if register is None:
                    raise ValueError(f"register_write names {op.register_id!r}, which is not a declared register: {sorted(r.id for r in plan.registers)}")
                if register.access == "RO":
                    raise ValueError(f"register_write targets read-only register {register.id}")
                if op.data >= 1 << register.width:
                    raise ValueError(f"register_write value does not fit the {register.width}-bit register {register.id}")
                if register.agent not in agents or not agents[register.agent].active:
                    raise ValueError(f"register_write needs the active agent that owns {register.id}")
                continue
            if op.register_id is not None:
                raise ValueError("Only register_write operations name a register")
            bus = op.kind in ("read", "write", "random_write", "poll")
            if ((agent.protocol=='custom' and op.kind!='custom') or
                    (agent.protocol!='custom' and (op.kind=='custom' or bus != (agent.protocol == "wishbone")))):
                raise ValueError("Sequence operation incompatible with its agent")
            width = ports[agent.bindings["wdata"]]["width"] if bus else agent.data_bits
            if max(op.data, op.mask) >= 1 << width:
                raise ValueError("Sequence value/mask exceeds transaction width")
            if bus and op.address >= 1 << ports[agent.bindings["addr"]]["width"]:
                raise ValueError("Sequence address exceeds interface width")
    for test in plan.tests:
        for stage in test.stages:
            if not stage or not set(stage) <= sequences.keys():
                raise ValueError("Test references unknown/empty sequence stage")
            ids = [sequences[name].agent for name in stage]
            if len(ids) != len(set(ids)):
                raise ValueError("Concurrent stage must not race sequences on the same sequencer")
    events = {"wishbone": {"write", "read"}, "serial": {"rx", "tx"}, "custom": {"transaction"}}
    for route in plan.routes:
        for condition in route.when:
            if condition.agent not in agents or agents[condition.agent].protocol!='wishbone':
                raise ValueError('Route qualification requires an observed bus register')
            agent=agents[condition.agent]
            if condition.address >= 1 << ports[agent.bindings['addr']]['width']:
                raise ValueError('Qualification address exceeds bus width')
            if max(condition.mask,condition.value,condition.initial_value or 0) >= 1 << ports[agent.bindings['wdata']]['width']:
                raise ValueError('Qualification value/mask exceeds bus width')
            if condition.value & ~condition.mask:
                raise ValueError('Qualification value must fit its comparison mask')
        for side in ("expected", "actual"):
            a = getattr(route, side + "_agent")
            if a not in agents or getattr(route, side + "_event") not in events[agents[a].protocol]:
                raise ValueError("Scoreboard route needs compatible monitored event kinds")
            agent=agents[a]
            width=ports[agent.bindings['wdata']]['width'] if agent.protocol=='wishbone' else agent.data_bits if agent.protocol=='serial' else 64
            if route.mask >= 1 << width:
                raise ValueError('Route comparison mask exceeds observed data width')
            address=getattr(route,side+'_address')
            if address is not None and (agent.protocol!='wishbone' or not 0 <= address < 1 << ports[agent.bindings['addr']]['width']):
                raise ValueError('Route address filter requires a valid bus address')
        if (route.expected_agent, route.expected_event, route.expected_address) == (route.actual_agent, route.actual_event, route.actual_address):
            raise ValueError("Scoreboard cannot compare an event against itself")
    bus = sorted(a for a in agents if agents[a].protocol == "wishbone")
    not_bus = [f"{c.id} (agent {c.agent})" for c in plan.checks if c.agent not in agents or agents[c.agent].protocol != "wishbone"]
    if not_bus:
        raise ValueError(f"Built-in protocol checks require a bus agent: {', '.join(not_bus)}. Bus agents: {bus or 'none'}. "
                         "The clock and reset are common UVCs, not agents; steps about them cannot be checks, so defer them as questions.")
    unknown = [f"{g.id} (agent {g.agent})" for g in plan.coverage if g.agent not in agents]
    if unknown:
        raise ValueError(f"Coverage goal references an unknown monitor agent: {', '.join(unknown)}. Agents: {sorted(agents)}. "
                         "The clock and reset are common UVCs, not agents; coverage of them cannot be declared here, so defer it as a question.")
    for goal in plan.coverage:
        agent=agents[goal.agent]
        names=[identifier(p.name) for p in goal.points]+[identifier(c.name) for c in goal.crosses]
        if len(names)!=len(set(names)): raise ValueError('Duplicate coverage point/cross names')
        for point in goal.points:
            if point.field=='address' and agent.protocol!='wishbone': raise ValueError('Address coverage requires a bus monitor')
            if point.field in ('parity_mode','stop_bits') and agent.protocol!='serial': raise ValueError('Frame coverage requires a serial monitor')
            bins=[identifier(b.name) for b in point.bins]
            if len(bins)!=len(set(bins)): raise ValueError('Duplicate coverage bins')
            width=(ports[agent.bindings['addr']]['width'] if point.field=='address' else
                   ports[agent.bindings['wdata']]['width'] if point.field=='data' and agent.protocol=='wishbone' else
                   agent.data_bits if point.field=='data' and agent.protocol=='serial' else
                   1 if point.field=='error' else 3 if point.field=='kind' else 64)
            selected_mask=(point.mask & ((1<<width)-1))>>point.shift
            for b in point.bins:
                if any(v<0 or v & ~selected_mask for v in b.values): raise ValueError('Coverage bin exceeds its selected field/mask width')
        point_names={p.name for p in goal.points}
        for cross in goal.crosses:
            if len(set(cross.points))!=len(cross.points) or not set(cross.points)<=point_names:
                raise ValueError('Coverage cross references unknown/duplicate points')
        allowed_kinds={'wishbone':{1,2},'serial':{3,4},'custom':{5}}[agent.protocol]
        if not set(goal.sample_kinds)<=allowed_kinds: raise ValueError('Coverage filter incompatible with monitored events')
        if goal.sample_address is not None and (agent.protocol!='wishbone' or goal.sample_address>=1<<ports[agent.bindings['addr']]['width']):
            raise ValueError('Coverage address filter requires a valid bus address')
    for hook in plan.hooks:
        if hook.slot=='coverage.sample' and hook.target in agents and not agents[hook.target].coverage_enabled:
            raise ValueError('Coverage hook requires selected coverage infrastructure')
        if hook.slot=='scoreboard.compare':
            if hook.target not in {r.id for r in plan.routes}: raise ValueError('Scoreboard hook requires a route target')
        elif hook.target not in agents:
            raise ValueError('Agent hook requires an agent target')
        elif hook.slot in ('driver.body','monitor.body') and agents[hook.target].protocol!='custom':
            raise ValueError('Protocol body hooks require the custom protocol; builtin behavior is template-owned')
    return ports


def validate_facts(facts,specification,sources):
    from ..quality.quick_testing import test_item_allowed
    if specification.get('source_authority')=='RTL_INFERRED':
        raise ValueError('Unvalidated RTL-derived expectations are not executable')
    bad=[f.id for f in facts if not is_identifier(f.id)]
    if bad: raise ValueError(f'Invalid fact identifiers {bad}: {IDENTIFIER_RULE}')
    ids=[identifier(f.id) for f in facts]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate fact IDs')
    for fact in facts:
        try: origin=pointer(specification,fact.plan_pointer)
        except (KeyError,IndexError,ValueError,TypeError):
            raise ValueError(f'Fact {fact.id} points outside the testplan') from None
        if not isinstance(origin,dict) or (origin.get('provenance')!='DOCUMENTED' and not test_item_allowed(specification,origin)):
            raise ValueError(f'Fact {fact.id} is not a documented plan item')
        if origin.get('cited_rtl_observation_ids') or origin.get('review_owner')=='RTL_DESIGN_ENGINEER':
            raise ValueError('RTL observations cannot supply executable expectations')
        allowed=set(origin.get('cited_chunk_ids',[]))|set(origin.get('cited_req_ids',[]))
        if origin.get('chunk_id'): allowed.add(origin['chunk_id'])
        allowed.update(s['chunk_id'] for s in origin.get('sources',[]) if isinstance(s,dict) and s.get('chunk_id'))
        if fact.source_id not in allowed or fact.source_id not in sources: raise ValueError(f'Fact {fact.id} lacks an eligible source')
        if locate_quote(sources[fact.source_id],fact.quote) is None: raise ValueError(f'Fact {fact.id} quote does not match its source')
