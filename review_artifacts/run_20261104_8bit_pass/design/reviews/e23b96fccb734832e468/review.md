## Decision needed

For wb_rst_i, is reset asserted high (1) or low (0)? Confirm the input name if more than one reset exists.

## Why this came up

The current evidence does not resolve this required binding: Is wb_rst_i asserted high (1) or low (0)? The specification text cited does not state it.

## Architecture and impact

Current implementation understanding (for review): The testbench supplies the reset; only its binding and active level is needed to generate it from the common UVC templates.
The reset driver needs the correct asserted level before bring-up. A wrong choice can leave the DUT in reset or prevent initialization.
- wb_rst_i: input relative to DUT, width 1

## Quick references

- [uart16550/doc/UART_spec.pdf — page 6](../../dv/testplan_doc.html#reference-CH-63ad4d61a5) [CH-63ad4d61a5; Specification reference]
  Excerpt offsets: 0–35
  > WB_RST_I 1 Input Asynchronous Reset

## Your decision

Reply in your own words with the intended setting and, if available, its reason.
I will restate the binding for you to confirm before recording approval.
Only this infrastructure clarification is approved; other behavior remains unchanged.
