# Choosing an RTL configuration from the request

Ask for the bus width in the request, for example `use the 8 bit version`, or name the macro: `define DATA_BUS_WIDTH_8`.
The orchestrator turns that into a compile define, and the define flows through the normal planning and code stages.
No design-specific table is used.

## How it works

1. `orchestrator_agent/request_defines.py` reads the RTL sources and collects the macro names they test or define
   (`` `ifdef``, `` `ifndef``, `` `elsif``, `` `define``).
2. A macro named outright in the request is selected.
3. A width phrase such as `8 bit` or `8-bit` selects the macro whose name carries that number **and** a bus or width
   word (`WIDTH`, `BUS`, `DATA`, `BITS`). A FIFO trigger level such as `UART_FC_8` is not a bus width and is ignored.
4. If a width phrase matches several such macros, nothing is selected and `/plan` is blocked with a question that names
   the candidates. Nothing is guessed.
5. The chosen defines go to `rtl_extract` and `rtl_build_graph` (`define` argument, `${rtl_defines:-}` in the flows). The
   interface JSON the code stage reads is then built with that configuration, so port widths and the bus roles follow it.
6. The ask card shows the selected configuration, or the open question, before `/plan`.

## Limits

- An unrelated phrase such as `FIFO trigger 8 bit` can still select the only 8-bit bus macro. The ask card shows it, so it
  can be checked before planning.
- The built-in bus driver supports the configurations its templates were verified for. The UART 8-bit configuration
  (`DATA_BUS_WIDTH_8`) is verified; the 32-bit byte-lane configuration is not supported by the built-in driver.
- The model-driven `/code` stage is not yet verified live with this configuration. Only the extraction and the wiring are verified.

## Verified

- `tests/test_request_defines.py` (7 tests): resolution on generic RTL, the multiple-candidate question, flow substitution,
  the extraction step on the real UART RTL (wb_dat_i 32 -> 8, wb_adr_i 5 -> 3), the full request -> define -> interface chain,
  and the ask card.
