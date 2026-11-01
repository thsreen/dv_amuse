# UART Interrupt collateral infrastructure

uart_interrupt is single-wire DUT-sourced sideband output int_o spec INT_O separate from bus and serial interfaces with empty protocol and unknown peer; unit-level passive observation exposes raw level and transitions for later-phase interrupt handling while SoC routing and functional checks remain deferred.

## Required actions

- Own uart_interrupt via single passive agent collateral_uart_interrupt observing RTL int_o as DUT-driven output with no driving
- Expose raw int_o level and transition visibility for later-phase use without protocol decoding or scoreboard
- Retain documented group context uart_interrupt function UART interrupt output with empty protocol and unknown peer without adding routing tie-offs or other interfaces

## Completion

- Passive ownership established: int_o observed only never driven per documented 1-bit Output
- Raw level and transition visibility available for deferred use with no functional contract
- No tie-offs target int_o and no other interfaces sequences tests or register mirrors added

## Deferred questions

- What active level should later-phase logic assume for int_o assertion given documented INT_O 1 Output Interrupt output leaves active_level undocumented, not needed for passive observation?
- On which clock edge should later-phase sampling of int_o transitions be aligned, deferred from passive infrastructure with no sampling requirement?
- Evidence substituted: f_int_o_port could not be proven from the retrieved sources (Fact must reference a retrieved documented item); the documented facts of this interface are cited instead. Review the choice that cited them.
