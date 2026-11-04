"""Quick testing only: one test chosen by script, so a prototype has a real pass.

The model's tests and routes share one scoreboard, so a test that does not exercise every route fails on the others. This
replaces them with one test built from what the model already established: its bus setup writes, the data address of its
receive route and the condition its routes put on that address. The test writes one byte out and receives one byte in, and
only those two paths are compared. Everything set aside is saved and listed as a question. Nothing here is design-specific.
"""
import json

from ..core.fsutil import atomic_write_text
from .contracts import Condition, Operation, Route, Sequence, Test

TEST_ID = 'quick_basic'
TX_DATA = 0x5A
RX_DATA = 0xA5
WRITE_KINDS = ('write', 'register_write')


def _setup_operations(plan, bus):
    """The first write-only bus sequence the model's tests run, else the first it declared. A sweep that rewrites an address is not a setup."""
    by_id = {s.id: s for s in plan.sequences}
    ordered = [by_id[sid] for t in plan.tests for stage in t.stages for sid in stage if sid in by_id] + list(plan.sequences)
    for sequence in ordered:
        addresses = [o.address for o in sequence.operations]
        if (sequence.agent == bus.id and len(addresses) >= 2 and all(o.kind in WRITE_KINDS for o in sequence.operations)
                and all(addresses.count(a) <= 2 for a in addresses)):
            return sequence
    return None


def _data_route(plan, bus, serial):
    """The route that names the data address, and its address: a receive or transmit path, else a write and read of one bus address."""
    for r in plan.routes:
        if r.expected_agent == serial.id and r.expected_event == 'rx' and r.actual_agent == bus.id and r.actual_event == 'read' and r.actual_address is not None:
            return r, r.actual_address
    for r in plan.routes:
        if r.expected_agent == bus.id and r.expected_event == 'write' and r.actual_agent == serial.id and r.actual_event == 'tx' and r.expected_address is not None:
            return r, r.expected_address
    for r in plan.routes:
        if (r.expected_agent == r.actual_agent == bus.id and r.expected_event == 'write' and r.actual_event == 'read'
                and r.expected_address == r.actual_address is not None and not r.when):
            return r, r.expected_address
    return None, None


def _data_condition(plan, bus, address, setup):
    """The state in which the address carries data. A path through the serial agent states it; a route from the bus to the bus at
    that address reaches something else there, so its condition is the opposite state. With neither, a condition the routes put on
    another address is taken in the state the setup leaves it."""
    at_address = [r for r in plan.routes if address in (r.expected_address, r.actual_address) and r.when and r.when[0].agent == bus.id]
    for route in at_address:
        if route.expected_agent != bus.id or route.actual_agent != bus.id:
            return [route.when[0].model_copy()]
    for route in at_address:
        c = route.when[0]
        return [Condition(agent=c.agent, address=c.address, mask=c.mask, value=c.value ^ c.mask, initial_value=c.initial_value)]
    for route in plan.routes:
        for c in route.when:
            writes = [o.data for o in setup.operations if o.address == c.address and o.kind in WRITE_KINDS]
            if c.agent == bus.id and writes:
                return [Condition(agent=c.agent, address=c.address, mask=c.mask, value=writes[-1] & c.mask, initial_value=c.initial_value)]
    return []


def apply_basic_test(plan, directory=None):
    """Replace the plan's tests and routes with the one test, or leave them and say why. Returns True when applied."""
    bus = next((a for a in plan.agents if a.protocol == 'wishbone' and a.active), None)
    serial = next((a for a in plan.agents if a.protocol == 'serial' and a.active), None)
    named, address = _data_route(plan, bus, serial) if bus and serial else (None, None)
    setup = _setup_operations(plan, bus) if bus else None
    if not (bus and serial and named and setup):
        plan.questions.append('Quick testing: the script-chosen test needs an active bus agent, an active serial agent, a route that names '
                              'the data address and a bus setup sequence; the model tests were kept.')
        return False
    condition = _data_condition(plan, bus, address, setup)
    mask = (1 << serial.data_bits) - 1
    frame = serial.bit_cycles * (serial.data_bits + serial.stop_bits + 3)  # start, parity and a margin
    facts = list(dict.fromkeys(named.fact_ids + setup.fact_ids))
    sequence = lambda sid, agent, purpose, *ops: Sequence(id=f'{TEST_ID}_{sid}', agent=agent, purpose=f'Script-chosen test: {purpose}',
                                                          operations=list(ops), fact_ids=facts)
    sequences = [
        sequence('setup', bus.id, 'the model setup writes', *[o.model_copy() for o in setup.operations]),
        sequence('write', bus.id, 'write one byte to transmit', Operation(kind='write', address=address, data=TX_DATA, mask=mask)),
        sequence('send', serial.id, 'send one byte to receive', Operation(kind='send', data=RX_DATA, mask=mask, cycles=frame)),
        sequence('read', bus.id, 'read the received byte', Operation(kind='idle', cycles=frame), Operation(kind='read', address=address)),
    ]
    routes = [
        Route(id=f'{TEST_ID}_transmit', expected_agent=bus.id, expected_event='write', expected_address=address, actual_agent=serial.id,
              actual_event='tx', when=condition, mask=mask, fact_ids=facts),
        Route(id=f'{TEST_ID}_receive', expected_agent=serial.id, expected_event='rx', actual_agent=bus.id, actual_event='read',
              actual_address=address, when=condition, mask=mask, fact_ids=facts),
    ]
    test = Test(id=TEST_ID, stages=[[s.id] for s in sequences], seed=1, drain_cycles=frame * 2, minimum_comparisons=2, fact_ids=facts)
    # A register mirrored at the data address would compare the received byte against the last write there.
    aliased = [r for r in plan.registers if r.agent == bus.id and r.address == address]
    aliased_ids = {r.id for r in aliased}
    for s in plan.sequences + sequences:
        for operation in s.operations:
            if operation.kind == 'register_write' and operation.register_id in aliased_ids:
                operation.kind, operation.register_id = 'write', None
    # The test uses only the bus and serial agents. A model hook on anything else cannot help it and can stop it finishing.
    dropped_hooks = [h for h in plan.hooks if h.target not in (bus.id, serial.id)]
    aside = dict(tests=[t.model_dump() for t in plan.tests], routes=[r.model_dump() for r in plan.routes],
                 registers=[r.model_dump() for r in aliased], hooks=[h.model_dump() for h in dropped_hooks])
    if directory is not None:
        atomic_write_text(directory/'quick_basic_set_aside.json', json.dumps(aside, indent=2)+'\n')
    plan.questions.append(f"Quick testing: {TEST_ID} is chosen by script, not designed by the model. Set aside to get a passing test: "
                          f"{len(aside['tests'])} model tests, {len(aside['routes'])} model routes, {len(aliased)} registers at the data address and "
                          f"{len(dropped_hooks)} hooks on agents and routes it does not use (quick_basic_set_aside.json). Only the transmit and receive paths are compared.")
    plan.sequences = plan.sequences + sequences
    plan.routes, plan.tests = routes, [test]
    plan.registers = [r for r in plan.registers if r.id not in aliased_ids]
    plan.hooks = [h for h in plan.hooks if h.target in (bus.id, serial.id)]
    return True
