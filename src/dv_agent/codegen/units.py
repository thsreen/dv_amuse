"""Ordered foundation units: clock, reset, then exactly one interface at a time."""
from typing import Literal

from pydantic import Field

from .contracts import Model, Fact, Agent, Register, TieOff, Hook, CodePlan, identifier
from .render import ROOT, template
from .validate import validate

CYCLE = ['retrieve', 'understand_and_pseudocode', 'implement', 'validate', 'checkpoint']


class ClockUnit(Model):
    top: str
    clock: str
    clock_period_ns: int = Field(default=10, ge=2, le=1000000)
    facts: list[Fact] = Field(min_length=1, max_length=16)


class ResetUnit(Model):
    reset: str
    reset_active: Literal['high', 'low']
    reset_cycles: int = Field(default=8, ge=2, le=10000)
    facts: list[Fact] = Field(min_length=1, max_length=16)


class InterfaceTask(Model):
    id: str
    title: str
    signals: list[str] = Field(min_length=1,max_length=32)
    queries: list[str] = Field(min_length=1,max_length=3)


class Interfaces(Model):
    interfaces: list[InterfaceTask] = Field(min_length=1,max_length=16)


class InterfaceUnit(Model):
    agents: list[Agent] = Field(default_factory=list,max_length=1)
    tie_offs: list[TieOff] = Field(default_factory=list,max_length=32)
    registers: list[Register] = Field(default_factory=list,max_length=16)
    hooks: list[Hook] = Field(default_factory=list,max_length=4)
    defines: list[str] = Field(default_factory=list,max_length=8)
    facts: list[Fact] = Field(min_length=1,max_length=32)
    questions: list[str] = Field(default_factory=list)


def foundation(run_unit, call, definition, evidence, check_facts, save, *, render_units=True):
    """A unit is saved and validated before its successor can start."""
    ports={p['name']:p for p in definition['ports']}
    def scalar(name):
        p=ports.get(name,{})
        if p.get('direction')!='input' or p.get('width',1)!=1 or p.get('range'):
            raise ValueError('Clock/reset must bind an explicit scalar DUT input')

    def clock_check(unit, context):
        identifier(unit.top);scalar(unit.clock);check_facts(unit.facts,context)
    clock=run_unit('foundation_clock','Clock','clock input, sampling edge, testbench period',
                   ['clock input sampling edge'],ClockUnit,clock_check,{},
                   'Select only the documented DUT clock and top. The generated period is a testbench operational setting.')
    if render_units:
        for p in sorted((ROOT.parent/'common_uvc/clock').iterdir()):
            if p.suffix in ('.sv','.svh'): save('units/clock/'+p.name,p.read_text())

    def reset_check(unit, context):
        scalar(unit.reset);check_facts(unit.facts,context)
        if unit.reset==clock.clock: raise ValueError('Clock and reset must differ')
    reset=run_unit('foundation_reset','Reset','reset polarity, assertion, release and bounded completion',
                   ['reset polarity assertion deassertion'],ResetUnit,reset_check,
                   dict(clock=clock.model_dump(exclude={'facts'})),
                   'Resolve only reset from its documented contract. Do not infer polarity from its name. '
                   'Reset cycles are a testbench operational setting; preserve any documented minimum.')
    if render_units:
        for p in sorted((ROOT.parent/'common_uvc/reset').iterdir()):
            if p.suffix in ('.sv','.svh'): save('units/reset/'+p.name,p.read_text())

    remaining=set(ports)-{clock.clock,reset.reset}
    def inventory_check(result):
        names=[];ids=[]
        for task in result.interfaces:
            identifier(task.id);ids.append(task.id);names+=task.signals
        if len(ids)!=len(set(ids)) or set(names)!=remaining or len(names)!=len(set(names)):
            raise ValueError('Interface inventory must assign each remaining DUT port exactly once')
    inventory=call('code_interfaces',dict(ports=[ports[n] for n in sorted(remaining)],
                       evidence=evidence.fetch(['interface signal protocol connected module'])),Interfaces,
                   'List compact interface task descriptors only: one physical protocol/function interface per task. '
                   'Assign every supplied port once, group related bus signals together. No behavior or implementation.',inventory_check)
    state=dict(top=clock.top,clock=clock.clock,reset=reset.reset,reset_active=reset.reset_active,
               clock_period_ns=clock.clock_period_ns,reset_cycles=reset.reset_cycles,
               facts=[],agents=[],tie_offs=[],registers=[],hooks=[],defines=[],questions=[])
    def facts(values):
        known={f['id']:f for f in state['facts']}
        for f in values:
            if f.id in known and known[f.id]!=f.model_dump(): raise ValueError('Conflicting foundation fact ID')
            known[f.id]=f.model_dump()
        return list(known.values())
    state['facts']=facts(clock.facts+reset.facts)
    for task in inventory.interfaces:
        scoped=dict(sources=definition.get('sources',[]),direction_reference='DUT',
                    ports=[ports[n] for n in task.signals])
        def interface_check(unit, context):
            check_facts(unit.facts,context)
            used=[name for a in unit.agents for name in a.bindings.values()]+[t.signal for t in unit.tie_offs]
            if set(used)!=set(task.signals) or len(used)!=len(set(used)):
                raise ValueError('Implement exactly this interface; bind or explicitly tie every assigned signal once')
            if unit.agents and unit.agents[0].id!=task.id: raise ValueError('Agent ID must match interface task ID')
            candidate=state|dict(facts=facts(unit.facts))
            for key in ('agents','registers','tie_offs','hooks','defines','questions'):
                candidate[key]=state[key]+getattr(unit,key)
            # Validate one interface against a scoped port set, without pretending
            # not-yet-implemented interfaces are tied off or already implemented.
            if candidate['agents']:
                validate(CodePlan.model_validate(candidate),{},dict(ports=[ports[n] for n in
                    ({clock.clock,reset.reset}|{v for a in candidate['agents'] for v in a.bindings.values()}|
                     {t.signal for t in candidate['tie_offs']})]),{},validate_source_facts=False)
        unit=run_unit('interface_'+task.id,task.title,'one interface agent, driver, monitor and coverage connection',
                      task.queries,InterfaceUnit,interface_check,
                      dict(clock=clock.model_dump(exclude={'facts'}),reset=reset.model_dump(exclude={'facts'})),
                      'Implement ONLY this interface. Return at most one agent with the task ID; tie-offs need source support. '
                      'Do not implement other interfaces, sequences, tests or the full register map. Use empty registers '
                      'unless a simple mirror is essential and explicitly documented; feature steps add mirrors later. '
                      'Declare custom driver/monitor hooks only for this interface when required.',scoped)
        state['facts']=facts(unit.facts)
        for key in ('agents','registers','tie_offs','hooks','defines','questions'):
            state[key]+=[v.model_dump() if hasattr(v,'model_dump') else v for v in getattr(unit,key)]
        if render_units:
            for agent in unit.agents:
                signals='\n'.join(f"  logic [{ports[name].get('width',1)-1}:0] {role};" for role,name in agent.bindings.items())
                save('units/'+task.id+'/'+task.id+'_if.sv',template('interface.sv',AGENT=agent.id,SIGNALS=signals))
    return CodePlan.model_validate(state)
