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
    if plan.clock_period_ranges:
        bins=[]
        for r in plan.clock_period_ranges:
            bins += [f'      bins {r.name}_min={{{r.min_ps}}};',f'      bins {r.name}_max={{{r.max_ps}}};']
            if r.nominal_ps is not None: bins += [f'      bins {r.name}_nominal={{{r.nominal_ps}}};']
            count=r.max_ps-r.min_ps+1
            for i in range(min(3,count)):
                lo=r.min_ps+i*count//min(3,count);hi=r.min_ps+(i+1)*count//min(3,count)-1
                bins += [f'      bins {r.name}_stratum_{i}={{[{lo}:{hi}]}};']
        add('uvm/cg_clock_coverage.svh',template('clock_coverage.svh',PERIOD_BINS='\n'.join(bins)))
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
        for component in (('cfg','sequencer') if a.active else ('cfg',)):
            add(f"uvm/{a.id}_{component}.svh", template(component + '.svh',
                VARIABLES='\n'.join(f'  bit [{v.width-1}:0] {v.id}={sv(v.default)};' for v in plan.sequencer_variables if v.agent==a.id), **values))
        for component in (('driver','monitor') if a.active else ('monitor',)):
            defaults={name:(1 if a.protocol=='serial' and role=='rx' else 0) for role,name in a.bindings.items() if ports[name]['direction']=='input'}
            defaults.update(a.idle_values)
            reset_assignments='\n'.join(f'    cfg.vif.{role} = {sv(defaults[name])};' for role,name in a.bindings.items() if name in defaults)
            if a.protocol=='wishbone' and 'sel' not in a.bindings: reset_assignments+="\n    cfg.vif.sel = '0;"
            text=template(a.protocol + '_' + component + '.svh',
                RESET_ASSIGNMENTS=reset_assignments,
                MONITOR_SIGNAL_DECLARATIONS='\n'.join(f'  logic [{w-1}:0] sampled_{r};' for r,w in widths.items()),
                MONITOR_RESET_ASSIGNMENTS='\n'.join(f"    sampled_{r} = '0;" for r in widths),
                MONITOR_SIGNAL_ASSIGNMENTS='\n'.join(f'    sampled_{r} = cfg.vif.{r};' for r in widths),
                DRIVER_HOOK=hook(a.id, 'driver.body'), MONITOR_HOOK=hook(a.id, 'monitor.body'), **values)
            add(f"uvm/{a.id}_{component}.svh",text)
        regs = [r for r in plan.registers if r.agent == a.id]
        bins = '\n'.join(f"bins {r.id}={{{i+1}}};" for i, r in enumerate(regs)) or 'bins not_register={0};'
        classes = '\n'.join(f"    if(observed.address=={sv(r.address)}) address_class={i+1};" for i, r in enumerate(regs))
        event_bins = ('bins writes={1}; bins reads={2};' if a.protocol == 'wishbone' else
                      'bins receive={3}; bins transmit={4};' if a.protocol=='serial' else 'bins observed={5};')
        if a.coverage_enabled:
            add(f"uvm/{a.id}_coverage.svh", template('coverage.svh', EVENT_BINS=event_bins, ADDRESS_BINS=bins,
                ADDRESS_CLASS=classes, DATA_MASK=sv((1 << data_width)-1), COVER_BITS=data_width,
                FRAME_COVERPOINTS=(f"    cp_parity: coverpoint parity_mode {{ bins configured={{{values['PARITY']}}}; }}\n"
                                  f"    cp_stop: coverpoint stop_bits {{ bins configured={{{a.stop_bits}}}; }}" if a.protocol=='serial' else ''),
                COVERAGE_HOOK=hook(a.id, 'coverage.sample'), **values))
        add(f"uvm/{a.id}_agent.svh", template('agent.svh' if a.active else 'passive_agent.svh',
            COVERAGE_MEMBER=f'  {a.id}_coverage cov;' if a.coverage_enabled else '',
            COVERAGE_BUILD=f'    cov={a.id}_coverage::type_id::create("cov",this); cov.cfg=cfg;' if a.coverage_enabled else '',
            COVERAGE_CONNECT='    mon.ap.connect(cov.analysis_export);' if a.coverage_enabled else '', **values))
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
                clock=f'@(posedge bus.clk) disable iff (bus.reset == {int(plan.reset_active=="high")})'
                properties += [f"  property p_{c.id}; {clock} ({trigger}) {delay} ({consequent}); endproperty",
                               f'  a_{c.id}: assert property(p_{c.id}) else $error("{c.id}");',
                               f"  c_{c.id}: cover property(p_{c.id});",
                               f"  activation_{c.id}: cover property({clock} {trigger});"]
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
    for goal in plan.coverage:
        points=[]
        for point in goal.points:
            bins=' '.join(f"bins {b.name}={{{', '.join(sv(v) for v in b.values)}}};" for b in point.bins)
            points.append(f'    {point.name}: coverpoint sampled_{point.name} {{ {bins} }}')
        filters=[]
        if goal.sample_kinds: filters.append('('+' || '.join(f'observed.kind=={k}' for k in goal.sample_kinds)+')')
        if goal.sample_address is not None: filters.append(f'observed.address=={sv(goal.sample_address)}')
        add(f'uvm/{goal.id}_coverage.svh',template('plan_coverage.svh',GOAL=goal.id,
            VARIABLES='\n'.join(f'  longint unsigned sampled_{p.name};' for p in goal.points),
            POINTS='\n'.join(points),CROSSES='\n'.join(f"    {c.name}: cross {', '.join(c.points)};" for c in goal.crosses),
            FILTER=' && '.join(filters) or '1',SAMPLING='\n'.join(
                f'      sampled_{p.name}=(observed.{p.field} & {sv(p.mask)}) >> {p.shift};' for p in goal.points)))
        env_members.append(f'  {goal.id}_coverage plan_cov_{goal.id};')
        env_build.append(f'    plan_cov_{goal.id}={goal.id}_coverage::type_id::create("plan_cov_{goal.id}",this);')
        env_connect.append(f'    {goal.agent}.mon.ap.connect(plan_cov_{goal.id}.analysis_export);')
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
    ordered=[];pending=list(plan.sequences)
    while pending:
        ready=[s for s in pending if not s.extends or s.extends in {p.id for p in ordered}]
        if not ready: raise ValueError('Cyclic or unknown base sequence')
        ordered+=ready
        pending=[s for s in pending if s not in ready]
    for seq in ordered:
        operations = ['    super.body();'] if seq.extends else []
        for index,op in enumerate(seq.operations):
            def value(field,default):
                binding=next((b for b in seq.controls if b.operation==index and b.field==field),None)
                return 'p_sequencer.'+binding.variable if binding else default
            kind = 0 if op.kind == 'idle' else 1 if op.kind in ('write', 'random_write') else 2 if op.kind == 'read' else 6 if op.kind=='poll' else 5 if op.kind=='custom' else 3
            operations += [f"    repeat({value('count',op.count)}) begin", '      tr=cg_item::type_id::create("request");',
                           '      start_item(tr);', f"      tr.kind={kind}; tr.address={value('address',sv(op.address))}; tr.mask={sv(op.mask)}; tr.cycles={value('cycles',op.cycles)};"]
            if op.kind.startswith('random_'):
                operations += ['      if(!tr.randomize()) `uvm_fatal("RAND", "randomization failed")', f"      tr.data &= {sv(op.mask)};"]
            else:
                operations += [f"      tr.data={value('data',sv(op.data))};"]
            operations += ['      finish_item(tr);', '    end']
        add(f"sequences/{seq.id}.svh", template('sequence.svh', SEQUENCE=seq.id, BASE=seq.extends or 'uvm_sequence #(cg_item)',
            SEQUENCER=f'  `uvm_declare_p_sequencer({seq.agent}_sequencer)' if seq.controls else '', OPERATIONS='\n'.join(operations)))
    # Per-test virtual sequences hold typed sequencer handles. They spawn only agent sequences.
    sequences = {s.id: s for s in plan.sequences}
    timing=[]
    if plan.clock_period_ranges:
        first=plan.clock_period_ranges[0]
        default_ps=first.nominal_ps if first.nominal_ps is not None else (first.min_ps+first.max_ps)//2
        allowed=' || '.join(f'(cg_clock_period_ps>={r.min_ps} && cg_clock_period_ps<={r.max_ps})' for r in plan.clock_period_ranges)
        timing=[f'    cg_clock_period_ps={default_ps};',
                '    void\'($value$plusargs("CLOCK_PERIOD_PS=%d",cg_clock_period_ps));',
                f'    if(!({allowed})) `uvm_fatal("CLOCK_RANGE", "Selected period is outside approved bands")',
                '    clk_cfg.period=real\'(cg_clock_period_ps) * 1ps;',
                '    $display("CLOCK_PERIOD_SELECTED_PS %0d",cg_clock_period_ps);']
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
                add(f"sequences/{drain_name}.svh", template('sequence.svh', SEQUENCE=drain_name, BASE='uvm_sequence #(cg_item)', SEQUENCER='',
                    OPERATIONS=f'    tr=cg_item::type_id::create("drain"); start_item(tr); tr.kind=0; tr.cycles={test.drain_cycles}; finish_item(tr);'))
                stages += [f"    begin {drain_name} drain; drain={drain_name}::type_id::create(\"drain\"); drain.start({a.id}_sqr); end"]
        add(f"sequences/{test.id}_vseq.svh", template('virtual_sequence.svh', TEST=test.id, DECLARATIONS='\n'.join(members), STAGES='\n'.join(stages)))
        test_members, test_build, handles = [], [], []
        for a in plan.agents:
            test_members += [f"  {a.id}_cfg {a.id}_control;"]
            test_build += [f'    {a.id}_control={a.id}_cfg::type_id::create("{a.id}_control");',
                           f'    if(!uvm_config_db #(virtual {a.id}_if)::get(this,"","{a.id}_vif",{a.id}_control.vif)) `uvm_fatal("VIF", "{a.id}_vif missing")',
                           f'    cmn_env.{a.id}_control={a.id}_control;']
            if a.active:
                handles += [f"    seq.{a.id}_sqr=cmn_env.{a.id}.sqr;"]
        for setting in test.sequencer_settings:
            variable=next(v for v in plan.sequencer_variables if v.id==setting.variable)
            handles += [f'    cmn_env.{variable.agent}.sqr.{variable.id}={sv(setting.value)};']
        if plan.clock_period_ranges:
            test_members += ['  cg_clock_coverage clock_cov;']
        add(f"tests/{test.id}.svh", template('test.svh', TEST=test.id, DECLARATIONS='\n'.join(test_members), BUILD='\n'.join(test_build),
            CLOCK_TIMING_SETUP='\n'.join(timing+(['    clock_cov=cg_clock_coverage::type_id::create("clock_cov",this);',
                '    clock_cov.expected_period_ps=cg_clock_period_ps;'] if plan.clock_period_ranges else [])), RESET_CYCLES=plan.reset_cycles,
            CLOCK_COVERAGE_CONNECT='    cmn_env.cmn_agent.clk_agent.mon.ap.connect(clock_cov.analysis_export);' if plan.clock_period_ranges else '',
            CLOCK_PERIOD=plan.clock_period_ns, RESET_ACTIVE=int(plan.reset_active=='high'), RESET_TIME=plan.clock_period_ns*plan.reset_cycles,
            MIN_COMPARISONS=test.minimum_comparisons, SEQUENCERS='\n'.join(handles),
            SYSTEM_COVERAGE_RESET=(f'    cmn_env.system_cov.reset_vif=rst_cfg.vif; cmn_env.system_cov.reset_active={int(plan.reset_active=="high")}; cmn_env.system_cov.flush();' if plan.routes else '')))
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
    from ..uvc import COMMON_UVCS, sources
    for kind in COMMON_UVCS:
        for p in sources(kind):
            artifacts[f'common_uvc/{kind}/{p.name}'] = p.read_text()
    compile_files = ['common_uvc/clock/clock_if.sv', 'common_uvc/reset/reset_if.sv',
                     'common_uvc/clock/clock_pkg.sv', 'common_uvc/reset/reset_pkg.sv',
                     'common_uvc/common/common_pkg.sv']
    compile_files += [f'interfaces/{a.id}_if.sv' for a in plan.agents]
    compile_files += [f'{package}.sv'] + [f'checks/{a.id}_assertions.sv' for a in plan.agents if any(c.agent==a.id for c in plan.checks)] + ['verification_top.sv']
    artifacts['compile.f'] = '\n'.join(compile_files)+'\n'
    artifacts['template_catalog.json'] = (ROOT/'catalog.json').read_text()
    return artifacts, compile_files
