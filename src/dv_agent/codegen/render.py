"""Pure rendering: validated protocol bindings + typed operations -> template artifacts."""
import json
import re
from pathlib import Path

from .contracts import digest

ROOT = Path(__file__).resolve().parents[1] / "templates" / "codegen"
EVENTS = {"write": 1, "read": 2, "rx": 3, "tx": 4, "transaction": 5}


def template(name, **values):
    source = (ROOT / (name + ".tmpl")).read_text()
    def replace(match):
        if match[1] not in values:
            raise ValueError(f"Missing template argument {name}.{match[1]}")
        return str(values[match[1]])
    return re.sub(r"\{\{([A-Z_]+)\}\}", replace, source)


def template_hash():
    return digest({p.name: p.read_text() for p in sorted(ROOT.iterdir()) if p.is_file()})


def sv(value):
    return f"64'h{value:x}"


def qualifiers(plan, variable):
    declarations, resets, updates, predicates = [], [], [], {}
    for route in plan.routes:
        parts=[]
        for i,condition in enumerate(route.when):
            name=f'qualification_{route.id}_{i}'
            declarations += [f"  longint unsigned {name};", f"  bit {name}_valid;"]
            resets += [f"    {name}={sv(condition.initial_value or 0)}; {name}_valid={int(condition.initial_value is not None)};"]
            updates += [f'    if({variable}.origin=="{condition.agent}" && {variable}.kind==1 && {variable}.address=={sv(condition.address)}) '
                        f'begin {name}={variable}.data; {name}_valid=1; end']
            parts.append(f'({name}_valid && ({name} & {sv(condition.mask)})=={sv(condition.value)})')
        predicates[route.id]=' && '+' && '.join(parts) if parts else ''
    return declarations,resets,updates,predicates


def render(plan, ports, hooks=None):
    hooks = hooks or {}
    artifacts, includes, connections, checker_instances = {}, [], {}, []
    top_declarations = [f"  wire [{p['width']-1}:0] dut_{name};" for name,p in ports.items()]
    package = plan.top + "_verification_pkg"
    def add(path, text):
        artifacts[path] = text
        if path.endswith('.svh'):
            includes.append(f'  `include "{path}"')
    def hook(target, slot):
        return '\n'.join(hooks[h.id] for h in plan.hooks if h.target == target and h.slot == slot and h.id in hooks)
    add("uvm/cg_item.svh", template("item.svh"))
    for a in plan.agents:
        widths = {role: ports[name]['width'] for role, name in a.bindings.items()}
        if a.protocol=='wishbone' and 'sel' not in widths:
            widths['sel']=1
        data_width = widths.get('wdata', a.data_bits)
        values = dict(AGENT=a.id, ACTIVE=int(a.active), RESET_ACTIVE=int(plan.reset_active == 'high'),
                      TIMEOUT=plan.request_timeout_cycles, BIT_CYCLES=a.bit_cycles, DATA_BITS=a.data_bits,
                      PARITY={'none': 0, 'even': 1, 'odd': 2}[a.parity], STOP_BITS=a.stop_bits, DATA_WIDTH=data_width)
        signals = '\n'.join(f"  logic [{width-1}:0] {role};" for role,width in widths.items())
        artifacts[f"interfaces/{a.id}_if.sv"] = template("interface.sv", SIGNALS=signals, **values)
        for component in ('cfg', 'sequencer'):
            add(f"uvm/{a.id}_{component}.svh", template(component + '.svh', **values))
        for component in ('driver', 'monitor'):
            add(f"uvm/{a.id}_{component}.svh", template(a.protocol + '_' + component + '.svh',
                DRIVER_HOOK=hook(a.id, 'driver.body'), MONITOR_HOOK=hook(a.id, 'monitor.body'), **values))
        regs = [r for r in plan.registers if r.agent == a.id]
        bins = '\n'.join(f"bins {r.id}={{{i+1}}};" for i, r in enumerate(regs)) or 'bins not_register={0};'
        classes = '\n'.join(f"    if(observed.address=={sv(r.address)}) address_class={i+1};" for i, r in enumerate(regs))
        event_bins = ('bins writes={1}; bins reads={2};' if a.protocol == 'wishbone' else
                      'bins receive={3}; bins transmit={4};' if a.protocol=='serial' else 'bins observed={5};')
        add(f"uvm/{a.id}_coverage.svh", template('coverage.svh', EVENT_BINS=event_bins, ADDRESS_BINS=bins,
            ADDRESS_CLASS=classes, DATA_MASK=sv((1 << data_width)-1), COVER_BITS=data_width,
            FRAME_COVERPOINTS=(f"    cp_parity: coverpoint parity_mode {{ bins configured={{{values['PARITY']}}}; }}\n"
                              f"    cp_stop: coverpoint stop_bits {{ bins configured={{{a.stop_bits}}}; }}" if a.protocol=='serial' else ''),
            COVERAGE_HOOK=hook(a.id, 'coverage.sample'), **values))
        add(f"uvm/{a.id}_agent.svh", template('agent.svh', **values))
        top_declarations.append(f"  {a.id}_if {a.id}_bus(clock_bus.clk, reset_bus.reset);")
        for role, name in a.bindings.items():
            if ports[name]['direction']=='input' and a.active:
                top_declarations.append(f"  assign dut_{name} = {a.id}_bus.{role};")
            else:
                top_declarations.append(f"  assign {a.id}_bus.{role} = dut_{name};")
        checks = [c for c in plan.checks if c.agent == a.id]
        if checks:
            properties = []
            for c in checks:
                trigger = "bus.cyc && bus.stb && !bus.ack" if c.kind == 'stable_until_ack' else "bus.cyc && bus.stb"
                consequent = "$stable({bus.addr,bus.wdata,bus.sel,bus.we})" if c.kind == 'stable_until_ack' else "!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})"
                delay = '|=>' if c.kind == 'stable_until_ack' else '|->'
                properties += [f"  property p_{c.id}; ({trigger}) {delay} ({consequent}); endproperty",
                               f'  a_{c.id}: assert property(p_{c.id}) else $error("{c.id}");',
                               f"  c_{c.id}: cover property(p_{c.id});",
                               f"  activation_{c.id}: cover property({trigger});"]
            artifacts[f"checks/{a.id}_assertions.sv"] = template('assertions.sv', PROPERTIES='\n'.join(properties), **values)
            checker_instances.append(f"  {a.id}_assertions {a.id}_checks({a.id}_bus);")
    declarations,reset,updates,predicates=qualifiers(plan,'tr')
    register_compare, route_compare, drain = [], list(updates), []
    for r in plan.registers:
        declarations += [f"  longint unsigned mirror_{r.id};", f"  bit valid_{r.id};"]
        reset += [f"    mirror_{r.id}={sv(r.reset or 0)}; valid_{r.id}={int(r.reset is not None)};"]
        register_compare += [f'    if(tr.origin=="{r.agent}" && tr.address=={sv(r.address)}) begin']
        if r.access in ('RW', 'WO'):
            register_compare += [f"      if(tr.kind==1) begin mirror_{r.id}=(mirror_{r.id} & ~{sv(r.mask)}) | (tr.data & {sv(r.mask)}); valid_{r.id}=1; end"]
        if r.access in ('RW', 'RO'):
            register_compare += [f"      if(tr.kind==2 && valid_{r.id}) begin comparisons++;",
                f'        if((tr.data & {sv(r.mask)}) != (mirror_{r.id} & {sv(r.mask)})) `uvm_error("REGISTER_MISMATCH", "{r.id}")', '      end']
        register_compare += ['    end']
    for route in plan.routes:
        name = route.id
        declarations += [f"  longint unsigned expected_{name}[$], actual_{name}[$];"]
        reset += [f"    expected_{name}.delete(); actual_{name}.delete();"]
        for side in ('expected', 'actual'):
            origin, event, addr = getattr(route, side + '_agent'), getattr(route, side + '_event'), getattr(route, side + '_address')
            addr_clause = '' if addr is None else f" && tr.address=={sv(addr)}"
            route_compare.append(f'    if(tr.origin=="{origin}" && tr.kind=={EVENTS[event]}{addr_clause}{predicates[name]}) {side}_{name}.push_back(tr.data & {sv(route.mask)});')
        route_compare += [f"    while(expected_{name}.size()!=0 && actual_{name}.size()!=0) begin",
                          f"      longint unsigned e, a; e=expected_{name}.pop_front(); a=actual_{name}.pop_front(); comparisons++;",
                          f'      if(e != a) `uvm_error("DATA_MISMATCH", $sformatf("{name}: expected=%h actual=%h", e,a))', '    end']
        drain += [f'    if(expected_{name}.size()!=0 || actual_{name}.size()!=0) `uvm_error("UNDRAINED", "{name}: unmatched observed transactions")']
    add('uvm/cg_scoreboard.svh', template('scoreboard.svh', DECLARATIONS='\n'.join(declarations), RESET_STATE='\n'.join(reset),
        REGISTER_COMPARE='\n'.join(register_compare), ROUTE_COMPARE='\n'.join(route_compare), DRAIN_CHECK='\n'.join(drain),
        SCOREBOARD_HOOK='\n'.join(hook(r.id, 'scoreboard.compare') for r in plan.routes)))
    route_bins,route_sampling=[],[]
    cov_declarations,cov_resets,cov_updates,cov_predicates=qualifiers(plan,'observed')
    for index,route in enumerate(plan.routes):
        for offset,side in enumerate(('expected','actual')):
            origin,event,addr=getattr(route,side+'_agent'),getattr(route,side+'_event'),getattr(route,side+'_address')
            number=index*2+offset
            route_bins.append(f"bins {route.id}_{side}={{{number}}};")
            addr_clause='' if addr is None else f" && observed.address=={sv(addr)}"
            route_sampling.append(f'    if(observed.origin=="{origin}" && observed.kind=={EVENTS[event]}{addr_clause}{cov_predicates[route.id]}) begin route_event={number}; samples++; interactions.sample(); end')
    if plan.routes:
        add('uvm/cg_system_coverage.svh',template('system_coverage.svh',ROUTE_BINS='\n'.join(route_bins),
            DECLARATIONS='\n'.join(cov_declarations), RESET_STATE='\n'.join(cov_resets), ROUTE_SAMPLING='\n'.join(cov_updates+route_sampling)))
    env_members, env_build, env_connect = [], [], []
    if plan.routes:
        env_members.append('  cg_system_coverage system_cov;')
        env_build.append('    system_cov=cg_system_coverage::type_id::create("system_cov",this);')
    for a in plan.agents:
        env_members += [f"  {a.id}_agent {a.id};", f"  {a.id}_cfg {a.id}_control;"]
        env_build += [f'    {a.id}={a.id}_agent::type_id::create("{a.id}",this); {a.id}.cfg={a.id}_control;']
        env_connect += [f"    {a.id}.mon.ap.connect(sb.analysis_export);"]
        if plan.routes:
            env_connect += [f"    {a.id}.mon.ap.connect(system_cov.analysis_export);"]
    add('uvm/cg_env.svh', template('env.svh', DECLARATIONS='\n'.join(env_members), BUILD='\n'.join(env_build), CONNECT='\n'.join(env_connect)))
    for seq in plan.sequences:
        operations = []
        for op in seq.operations:
            kind = 0 if op.kind == 'idle' else 1 if op.kind in ('write', 'random_write') else 2 if op.kind == 'read' else 6 if op.kind=='poll' else 5 if op.kind=='custom' else 3
            operations += [f"    repeat({op.count}) begin", '      tr=cg_item::type_id::create("request");',
                           '      start_item(tr);', f"      tr.kind={kind}; tr.address={sv(op.address)}; tr.mask={sv(op.mask)}; tr.cycles={op.cycles};"]
            if op.kind.startswith('random_'):
                operations += ['      if(!tr.randomize()) `uvm_fatal("RAND", "randomization failed")', f"      tr.data &= {sv(op.mask)};"]
            else:
                operations += [f"      tr.data={sv(op.data)};"]
            operations += ['      finish_item(tr);', '    end']
        add(f"sequences/{seq.id}.svh", template('sequence.svh', SEQUENCE=seq.id, OPERATIONS='\n'.join(operations)))
    # Per-test virtual sequences hold typed sequencer handles. They spawn only agent sequences.
    sequences = {s.id: s for s in plan.sequences}
    for test in plan.tests:
        members = [f"  {a.id}_sequencer {a.id}_sqr;" for a in plan.agents if a.active]
        stages = []
        for index, stage in enumerate(test.stages):
            stages += ['    fork']
            for name in stage:
                seq = sequences[name]
                stages += [f"      begin {name} seq_{index}_{name};", f'        seq_{index}_{name}={name}::type_id::create("seq_{index}_{name}");',
                           f"        seq_{index}_{name}.start({seq.agent}_sqr); end"]
            stages += ['    join']
        for a in plan.agents:
            if a.active:
                drain_name = f"{test.id}_{a.id}_drain"
                add(f"sequences/{drain_name}.svh", template('sequence.svh', SEQUENCE=drain_name,
                    OPERATIONS=f'    tr=cg_item::type_id::create("drain"); start_item(tr); tr.kind=0; tr.cycles={test.drain_cycles}; finish_item(tr);'))
                stages += [f"    begin {drain_name} drain; drain={drain_name}::type_id::create(\"drain\"); drain.start({a.id}_sqr); end"]
        add(f"sequences/{test.id}_vseq.svh", template('virtual_sequence.svh', TEST=test.id, DECLARATIONS='\n'.join(members), STAGES='\n'.join(stages)))
        test_members, test_build, handles = [], [], []
        for a in plan.agents:
            test_members += [f"  {a.id}_cfg {a.id}_control;"]
            test_build += [f'    {a.id}_control={a.id}_cfg::type_id::create("{a.id}_control");',
                           f'    if(!uvm_config_db #(virtual {a.id}_if)::get(this,"","{a.id}_vif",{a.id}_control.vif)) `uvm_fatal("VIF", "{a.id}_vif missing")',
                           f'    env.{a.id}_control={a.id}_control;']
            if a.active:
                handles += [f"    seq.{a.id}_sqr=env.{a.id}.sqr;"]
        add(f"tests/{test.id}.svh", template('test.svh', TEST=test.id, DECLARATIONS='\n'.join(test_members), BUILD='\n'.join(test_build),
            CLOCK_PERIOD=plan.clock_period_ns, RESET_ACTIVE=int(plan.reset_active=='high'), RESET_TIME=plan.clock_period_ns*plan.reset_cycles,
            MIN_COMPARISONS=test.minimum_comparisons, SEQUENCERS='\n'.join(handles),
            SYSTEM_COVERAGE_RESET=(f'    env.system_cov.reset_vif=reset_control.vif; env.system_cov.reset_active={int(plan.reset_active=="high")}; env.system_cov.flush();' if plan.routes else '')))
    # Includes are sorted by construction, not lexicographically: dependencies precede users.
    artifacts[f"{package}.sv"] = template('package.sv', PACKAGE=package, INCLUDES='\n'.join(includes))
    connections = {name: 'dut_'+name for name in ports}
    top_declarations += [f"  assign dut_{plan.clock}=clock_bus.clk;", f"  assign dut_{plan.reset}=reset_bus.reset;"]
    for t in plan.tie_offs:
        top_declarations += [f"  assign dut_{t.signal}={sv(t.value)};"]
    artifacts['verification_top.sv'] = template('top.sv', PACKAGE=package, TOP=plan.top,
        DECLARATIONS='\n'.join(top_declarations), DUT_CONNECTIONS=', '.join(f'.{n}({v})' for n,v in connections.items()),
        CHECKERS='\n'.join(checker_instances), DEFAULT_TEST=plan.tests[0].id if plan.tests else '',
        CONFIG='\n'.join(f'    uvm_config_db #(virtual {a.id}_if)::set(null,"uvm_test_top","{a.id}_vif",{a.id}_bus);' for a in plan.agents))
    common = ROOT.parent / 'common_uvc'
    for kind in ('clock', 'reset'):
        for p in sorted((common/kind).iterdir()):
            if p.suffix in ('.sv', '.svh'):
                artifacts[f'common_uvc/{kind}/{p.name}'] = p.read_text()
    compile_files = ['common_uvc/clock/clock_if.sv', 'common_uvc/reset/reset_if.sv',
                     'common_uvc/clock/clock_pkg.sv', 'common_uvc/reset/reset_pkg.sv']
    compile_files += [f'interfaces/{a.id}_if.sv' for a in plan.agents]
    compile_files += [f'{package}.sv'] + [f'checks/{a.id}_assertions.sv' for a in plan.agents if any(c.agent==a.id for c in plan.checks)] + ['verification_top.sv']
    artifacts['compile.f'] = '\n'.join(compile_files)+'\n'
    artifacts['template_catalog.json'] = (ROOT/'catalog.json').read_text()
    return artifacts, compile_files
