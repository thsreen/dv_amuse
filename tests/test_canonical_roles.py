"""Protocol role names are owned by the template; a model's own names are mapped onto them or left to fail."""
from dv_agent.codegen.validate import canonical_roles

PORTS = {n: dict(direction=d, width=w) for n, d, w in [
    ('p_adr', 'input', 5), ('p_dat_i', 'input', 32), ('p_dat_o', 'output', 32), ('p_sel', 'input', 4), ('p_we', 'input', 1),
    ('p_stb', 'input', 1), ('p_cyc', 'input', 1), ('p_ack', 'output', 1)]}
WANT = {'addr': 'p_adr', 'wdata': 'p_dat_i', 'rdata': 'p_dat_o', 'sel': 'p_sel', 'we': 'p_we', 'stb': 'p_stb', 'cyc': 'p_cyc', 'ack': 'p_ack'}


def test_descriptive_role_names_map_onto_the_protocol_roles():
    named = {'address': 'p_adr', 'select': 'p_sel', 'write_data': 'p_dat_i', 'read_data': 'p_dat_o', 'write_enable': 'p_we',
             'strobe': 'p_stb', 'cycle': 'p_cyc', 'acknowledge': 'p_ack'}
    assert canonical_roles('wishbone', named, PORTS) == WANT


def test_invented_names_fall_back_to_the_port_names():
    named = {f'tb_master_{i}': n for i, n in enumerate(WANT.values())}
    assert canonical_roles('wishbone', named, PORTS) == WANT


def test_already_canonical_unknown_protocol_and_ambiguous_bindings_are_left_alone():
    assert canonical_roles('wishbone', WANT, PORTS) is WANT
    other = {'x': 'p_adr'}
    assert canonical_roles('custom', other, PORTS) is other
    ambiguous = {'foo': 'p_adr', 'bar': 'p_adr'}
    assert canonical_roles('wishbone', ambiguous, PORTS) is ambiguous  # two bindings, one role
    unmatched = {'zzz': 'p_adr'}
    assert canonical_roles('wishbone', unmatched, {'p_adr': dict(direction='input', width=1)} | {}) == {'addr': 'p_adr'}  # the port name decides
    nothing = {'qq': 'p_x'}
    assert canonical_roles('wishbone', nothing, {'p_x': dict(direction='input', width=1)}) is nothing


def test_serial_role_names_map_by_the_model_name_or_the_port_name():
    ports = {'srx_pad_i': dict(direction='input', width=1), 'stx_pad_o': dict(direction='output', width=1)}
    assert canonical_roles('serial', {'serial_rx': 'srx_pad_i', 'serial_tx': 'stx_pad_o'}, ports) == {'rx': 'srx_pad_i', 'tx': 'stx_pad_o'}
    assert canonical_roles('serial', {'a': 'srx_pad_i', 'b': 'stx_pad_o'}, ports) == {'rx': 'srx_pad_i', 'tx': 'stx_pad_o'}  # port names decide
    # Names that contradict the port directions are ignored; the ports' own names and directions decide.
    assert canonical_roles('serial', {'serial_rx': 'stx_pad_o', 'serial_tx': 'srx_pad_i'}, ports) == {'rx': 'srx_pad_i', 'tx': 'stx_pad_o'}
    two_inputs = {'p': dict(direction='input', width=1), 'q': dict(direction='input', width=1)}
    unmatched = {'serial_rx': 'p', 'serial_tx': 'q'}
    assert canonical_roles('serial', unmatched, two_inputs) is unmatched  # a transmit role needs an output: nothing is forced


def test_ports_that_fill_every_bus_role_are_a_bus_whatever_the_model_called_the_agent():
    from dv_agent.codegen.validate import builtin_protocol
    named = {'address': 'p_adr', 'select': 'p_sel', 'write_data': 'p_dat_i', 'read_data': 'p_dat_o', 'write_enable': 'p_we',
             'strobe': 'p_stb', 'cycle': 'p_cyc', 'acknowledge': 'p_ack'}
    assert builtin_protocol(named, PORTS) == ('wishbone', WANT)
    no_sel = {k: v for k, v in WANT.items() if k != 'sel'}
    assert builtin_protocol(no_sel, {n: PORTS[n] for n in no_sel.values()})[0] == 'wishbone'  # the byte select is optional
    missing_strobe = {k: v for k, v in named.items() if k != 'strobe'}
    assert builtin_protocol(missing_strobe, PORTS) == (None, missing_strobe)  # an incomplete bus stays custom
    extra = dict(named, other='p_extra')
    assert builtin_protocol(extra, dict(PORTS, p_extra=dict(direction='input', width=1)))[0] is None
    serial_ports = {'srx_pad_i': dict(direction='input', width=1), 'stx_pad_o': dict(direction='output', width=1)}
    assert builtin_protocol({'serial_rx': 'srx_pad_i', 'serial_tx': 'stx_pad_o'}, serial_ports) == ('serial', {'rx': 'srx_pad_i', 'tx': 'stx_pad_o'})
