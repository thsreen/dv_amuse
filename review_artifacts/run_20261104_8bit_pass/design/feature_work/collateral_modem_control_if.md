# Modem control handshake interface collateral infrastructure

Modem control is a sideband flow_control utility to an external modem peer, separate from serial data. This collateral provides one bidirectional agent that drives the four DUT status inputs and observes the two DUT control outputs, reusing wb_clk_i and wb_rst_i base and spec_rtl_relation RTL names, leaving scoreboard, tests and register mirrors to later phases.

## Required actions

- Create single utility agent collateral_modem_control_if owning rts_pad_o, dtr_pad_o, cts_pad_i, dsr_pad_i, ri_pad_i and dcd_pad_i per spec_rtl_relation identity map
- Configure drive ownership for DUT inputs cts_pad_i, dsr_pad_i, ri_pad_i and dcd_pad_i with template drive_reset_values defaults
- Configure observe-only for DUT outputs rts_pad_o and dtr_pad_o without driving
- Bind agent to external modem peer as sideband flow_control with empty protocol requiring no additional protocol configuration
- Integrate with existing wb_clk_i and wb_rst_i base without adding clock, reset or other-interface collateral

## Completion

- Ownership declared for all six modem ports with drive for cts_pad_i, dsr_pad_i, ri_pad_i, dcd_pad_i and observe for rts_pad_o, dtr_pad_o
- Agent bound to external modem peer as sideband flow_control with no protocol configuration required
- No tie-offs on active agent ports and no other interfaces, sequences, tests or register mirrors implemented

## Deferred questions

- What DUT sampling edge if any applies to cts_pad_i, dsr_pad_i, ri_pad_i, dcd_pad_i and rts_pad_o, dtr_pad_o for later monitor phases?
- Is any modem status change or interrupt mapping needed for later scoreboard and functional phases?
- Evidence substituted: f_peer_1, port_dcd_pad_i, port_dtr_pad_o, port_rts_pad_o could not be proven from the retrieved sources (Fact must reference a retrieved documented item); the documented facts of this interface are cited instead. Review the choice that cited them.
