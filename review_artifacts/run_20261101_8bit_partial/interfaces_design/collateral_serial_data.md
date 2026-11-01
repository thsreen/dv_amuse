# Serial Data collateral infrastructure

serial_data is the off-chip UART RS232 bidirectional data path to modem/external device with stx_pad_o output and srx_pad_i input. A single bidirectional external_device agent collateral_serial_data provides drive/observe ownership at the top boundary, exposing transmit observation and receive stimulus to later protocol layers while clock, reset and modem-control sideband remain separate units; no tie-off or scoreboard is needed for this ownership.

## Required actions

- Instantiate one bidirectional protocol agent collateral_serial_data for serial_data external_device endpoint using spec_rtl_relation RTL names stx_pad_o and srx_pad_i
- Drive srx_pad_i from collateral_serial_data agent with test-only idle_values 1 for UART mark idle and observe stx_pad_o transmit without permanent tie-off
- Observe srx_pad_i in same bidirectional agent for visibility and declare RS232 UART transmit-receive function toward modem or other external devices
- Apply drive_reset_values defaults for owned input and retain RS232 protocol declaration with no scoreboard, transaction, monitor or coverage

## Completion

- collateral_serial_data agent owns srx_pad_i drive with idle 1 and stx_pad_o plus srx_pad_i observe as RS232 bidirectional endpoint
- No tie-off targets active agent ports and no runnable test, oracle, scoreboard comparison, protocol transaction, monitor or coverage required for infrastructure completion

## Deferred questions

- serial_data stx_pad_o/srx_pad_i: sources document 1-bit RS232 bidirectional pads to modem/external device but leave baud-derived bit timing and DUT sampling edge unspecified — confirm infrastructure stays declaration plus drive/observe ownership now with timing/line-format reconstruction deferred to later phase, since timing affects future transaction monitoring but not current ownership?
- Evidence substituted: f_peer could not be proven from the retrieved sources (Fact f_peer lacks an eligible source); the documented facts of this interface are cited instead. Review the choice that cited them.
