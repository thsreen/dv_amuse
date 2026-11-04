# Interrupt output interface collateral infrastructure

DUT sources single-wire 1-bit INT_O as int_o interrupt sideband; collateral_interrupt_output provides passive observe-only ownership exposing assertion and deassertion edges for later correlation with WISHBONE handling and SoC interrupt routing, while wb_clk_i wb_rst_i and all other interfaces remain owned elsewhere with no driving tie-offs checks or coverage in this unit.

## Required actions

- Declare passive agent collateral_interrupt_output owning observe-only access to int_o mapped from INT_O per spec_rtl_relation normalized_name PASS
- Configure monitor to passively observe 1-bit DUT-output int_o assertion and deassertion edges without driving and with no tie-offs
- Expose observed int_o transition events for later-phase correlation without implementing checks scoreboard coverage sequences or tests
- Leave wb_clk_i clocking wb_rst_i reset control and all other interfaces to owning infrastructures

## Completion

- Passive observe-only ownership of int_o declared from documented INT_O 1-bit Output
- DUT-source direction and sideband observation configuration complete with no inputs driven and no tie-offs
- Event exposure ready for later-phase use with scoreboard tests and full register map explicitly deferred

## Deferred questions

- How should observed int_o edges be interpreted in later phases when active_level is undocumented for documented INT_O 1-bit Output Interrupt output?
- On which sampling reference should int_o be observed for later-phase event correlation, deferred from this observe-only infrastructure?
