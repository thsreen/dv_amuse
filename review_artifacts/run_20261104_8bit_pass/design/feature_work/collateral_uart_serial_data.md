# UART serial data interface collateral infrastructure

uart_serial_data is the bidirectional RS232 serial data link STX_PAD_O output plus SRX_PAD_I input to modem or other external devices; infrastructure provides single full_agent ownership to drive SRX and observe STX with byte-framing driver/monitor hooks coordinated with the WISHBONE payload path, deferring scoreboard, tests, coverage, and register map.

## Required actions

- Create single uart_serial_data agent for collateral_uart_serial_data owning srx_pad_i drive and stx_pad_o observe per PASS RTL mappings stx_pad_o/srx_pad_i
- Drive srx_pad_i as active RS232 serial input stimulus with driver default from drive_reset_values
- Observe stx_pad_o as DUT-driven RS232 serial output
- Provide uart_serial_data driver/monitor/sequencer hooks for TX/RX byte framing to external_device peer
- Model bidirectional modem or other external devices connectivity over serial cable without implementing other interfaces, scoreboard, tests, or full register map

## Completion

- srx_pad_i drive ownership established from documented input direction
- stx_pad_o observe responsibility established from documented output direction
- uart_serial_data full_agent driver plus monitor collateral present for RS232 external_device link
- No scoreboard, functional tests, coverage, or full register map added

## Deferred questions

- For uart_serial_data srx_pad_i/stx_pad_o: documented sources confirm RS232 external-device link and input/output directions but do not specify frame parameters and divisor-to-baud sampling reference; what baud/frame configuration should the full_agent use to drive SRX and reconstruct STX bytes and coordinate with WISHBONE payload in later phases?
- Evidence substituted: f_stx_port could not be proven from the retrieved sources (Fact must reference a retrieved documented item); the documented facts of this interface are cited instead. Review the choice that cited them.
