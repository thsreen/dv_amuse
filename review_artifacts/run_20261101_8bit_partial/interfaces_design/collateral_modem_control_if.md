# Modem Control collateral infrastructure

Modem control is six 1-bit sideband handshake pads to an external modem peer separate from serial data, with two DUT outputs to observe and four DUT inputs to drive; collateral owns this interface alone under wb_clk_i and wb_rst_i operations for later Wishbone MCR-MSR coordination without functional checking in this phase.

## Required actions

- Claim sole ownership of modem_control pads rts_pad_o, dtr_pad_o, cts_pad_i, dsr_pad_i, ri_pad_i, dcd_pad_i in single collateral_modem_control_if endpoint using RTL names from shared identity map
- Configure testbench to drive cts_pad_i, dsr_pad_i, ri_pad_i, dcd_pad_i and observe rts_pad_o, dtr_pad_o per documented DUT input-output directions
- Apply template drive_reset_values generic 0 to all owned inputs with no register mirrors and no tie-offs on actively owned ports
- Expose logical-level observation of rts_pad_o and dtr_pad_o for later Wishbone MCR-MSR coordination with no functional checking in this phase
- Verify collateral readiness for modem_control only leaving serial data, Wishbone, clocks and resets to their own units

## Completion

- Ownership recorded for all six modem pads with DUT output direction for rts_pad_o-dtr_pad_o and input direction for cts_pad_i-dsr_pad_i-ri_pad_i-dcd_pad_i preserved
- Single collateral_modem_control_if endpoint drives four status inputs and observes two control outputs with generic reset defaults
- No tie-offs on actively owned ports, no other interfaces implemented, no register mirrors added
- Infrastructure ready for later MCR-MSR sequencing pending deferred polarity interpretation

## Deferred questions

- For later functional use of rts_pad_o, dtr_pad_o, cts_pad_i, dsr_pad_i, ri_pad_i, dcd_pad_i: spec documents names, directions and descriptions but active_level is undocumented, what asserted polarity and MCR inversion applies? Infrastructure proceeds at logical levels.
- What DUT sampling and timing relationship applies to modem status inputs and control outputs relative to wb_clk_i for later stimulus coordination? Deferred sequencing detail only.
- Evidence substituted: f_modem_peer, port_dcd_pad_i, port_dsr_pad_i, port_dtr_pad_o, port_ri_pad_i, port_rts_pad_o could not be proven from the retrieved sources (Fact must reference a retrieved documented item); the documented facts of this interface are cited instead. Review the choice that cited them.
