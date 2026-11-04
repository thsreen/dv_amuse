## Decision needed

Confirm the selected interface wiring and configuration:
- CLK: spec width 1, direction input; RTL candidates wb_clk_i
- WB_ADDR_I: spec width 5 or 3, direction input; RTL candidates wb_adr_i
- WB_DAT_I: spec width 32 or 8, direction input; RTL wb_dat_i width 8
- WB_DAT_O: spec width 32 or 8, direction output; RTL wb_dat_o width 8
- BAUD_O: spec width 1, direction output; optional under if UART_HAS_BAUDRATE_OUTPUT is defined; absent from RTL

## Why this came up

The current evidence does not resolve this required binding: CLK: spec width 1, direction input; RTL candidates wb_clk_i; WB_ADDR_I: spec width 5 or 3, direction input; RTL candidates wb_adr_i

## Architecture and impact

Current implementation understanding (for review): The specification describes the logical interface and permitted variants. The configured RTL inventory defines physical port names and selected widths. Confirm aliases and the selected variant together before any interface or driver is built. Optional-port absence needs an explicit configuration decision.
These decisions connect specification signals to physical RTL ports. They must pass independent validation before SV interfaces or verification code can be generated.
- wb_clk_i: input relative to DUT, width 1
- wb_adr_i: input relative to DUT, width 3
- wb_dat_i: input relative to DUT, width 8
- wb_dat_o: output relative to DUT, width 8

## Quick references

- [uart16550/doc/UART_spec.pdf — page 6](../../dv/testplan_doc.html#reference-CH-63ad4d61a5) [CH-63ad4d61a5; Specification reference]
  > CLK 1 Input Block’s clock input
- [uart16550/doc/UART_spec.pdf — page 6](../../dv/testplan_doc.html#reference-CH-63ad4d61a5) [CH-63ad4d61a5; Specification reference]
  > WB_ADDR_I 5 or 3 Input Used for register selection
- [uart16550/doc/UART_spec.pdf — page 6](../../dv/testplan_doc.html#reference-CH-63ad4d61a5) [CH-63ad4d61a5; Specification reference]
  > WB_DAT_I 32 or 8 Input Data input
- [uart16550/doc/UART_spec.pdf — page 6](../../dv/testplan_doc.html#reference-CH-63ad4d61a5) [CH-63ad4d61a5; Specification reference]
  > WB_DAT_O 32 or 8 Output Data output
- [uart16550/doc/UART_spec.pdf — page 6](../../dv/testplan_doc.html#reference-CH-8c2c8e9408) [CH-8c2c8e9408; Specification reference]
  > BAUD_O 1 Output Optional baud rate output signal.
  > The signal here is the 16 x actual baud rate.
  > It is enabled if UART_HAS_BAUDRATE_OUTPUT
  > is defined

## Your decision

Reply in your own words with the intended setting and, if available, its reason.
I will restate the binding for you to confirm before recording approval.
Only this infrastructure clarification is approved; other behavior remains unchanged.
