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
6. The interface JSON records its `defines`, and the build compiles the RTL with exactly those, so the simulated design
   matches the interface. An explicit code contract may add defines; a model may not.
7. A saved run with a different configuration is not restored, so `/code` never reuses a plan built for another one.
8. On a narrow bus the byte-select port still exists but is unused: it is held at 0 (`codegen/normalize.py`).
9. The ask card shows the selected configuration, or the open question, before `/plan`.

## The test plan follows the same configuration (`plan/configuration.py`)

With a define selected, the plan describes that build only. The other modes are found from the specification's own width
alternatives (`32 or 8` with an 8-bit selection leaves 32 as the other mode; `5 or 3` does not name another bus mode).

- **Interfaces:** a signal shows `8 (this build; documented: 32 or 8)`. The documented width is kept, so the port comparison
  and its audit see the same inventory. A conditional port this build lacks is marked inactive and left out of the tables.
- **Registers:** a register available only in another mode, with its fields and conflicts, leaves the map before any section uses it.
- **Model sections:** each receives `rtl_configuration` and a rule to plan only for it; strategy gets the same rule.
- **Final guard:** an entry that still mentions another mode leaves the plan, and an assertion whose cover left with it goes
  too, keeping the assertion/cover pairing. Generated strategy or configuration prose cannot be cut safely, so a mention there
  is flagged `NEEDS_REVIEW`.
- **Visible:** the plan states its configuration at the top and lists everything left out, with reasons, in a collapsible block.

Quotes in the references remain verbatim specification evidence and can mention other modes. With no define selected the plan
is unchanged.

## Limits

- An unrelated phrase such as `FIFO trigger 8 bit` can still select the only 8-bit bus macro. The ask card shows it, so it
  can be checked before planning.
- The final guard matches a stated width such as `32-bit`. A statement about another mode that names no width relies on the
  prompt rule alone.
- The built-in bus driver supports the configurations its templates were verified for. The UART 8-bit configuration
  (`DATA_BUS_WIDTH_8`) is verified; the 32-bit byte-lane configuration is not supported by the built-in driver.
- The model-driven `/code` stage is not yet verified live with this configuration. Extraction, compile and simulation are verified
  from an explicit contract.

## Verified

- `tests/test_request_defines.py` (7 tests): resolution on generic RTL, the multiple-candidate question, flow substitution,
  the extraction step on the real UART RTL (wb_dat_i 32 -> 8, wb_adr_i 5 -> 3), the full request -> define -> interface chain,
  the ask card, and saved-run matching.
- `tests/test_plan_configuration.py` (12 tests), and a replay on a real saved plan with the real 8-bit interface: widths 3 and 8
  shown, `BAUD_O` and the two debug registers out, port comparison unchanged. No live model plan has been generated with it yet.
- Real Xezim + UVM: request -> flow extraction from the top file -> compile and run PASS with no define in the contract
  (`DV_AGENT_TEST_SIMULATION=1 pytest tests/test_request_defines.py -k real_uart`).
