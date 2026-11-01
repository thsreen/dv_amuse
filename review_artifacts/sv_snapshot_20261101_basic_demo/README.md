# Temporary SV review snapshot: basic demo (register writes and one packet each way)

This directory is a removable review copy. Nothing in the generator imports it. Delete this entire
`review_artifacts/sv_snapshot_20261101_basic_demo/` directory when review is complete, or revert its commit.

## What it is

The SystemVerilog/UVM testbench produced by `/code demo basic` (`demo_scripts/uart_top.json`) on a copy of a real
quick-testing run: that run's own plan, interface and port-alignment approvals. It was built with **no model call**
and simulated under Xezim 0.11.3 with UVM 2020.3.1: compile PASS, run PASS, 3 scoreboard comparisons, 0 UVM errors
(`validation.json`). It is **not** an autonomous model-generated testbench, and passing it is not functional sign-off.

What the one test (`basic_demo`) exercises:

1. named register writes through `cg_reg_access::write` (divisor, framing, FIFO control);
2. a read-back of the line-control register (comparison 1);
3. one byte written to the transmit register and checked on the serial output (comparison 2);
4. one byte driven on the serial input and read back from the bus (comparison 3).

Every source file starts with the quick-testing warning: the plan items it used are test-only approvals.

## Configuration

The script is written for the 8-bit bus configuration (`DATA_BUS_WIDTH_8`); the run's interface was re-extracted with
that define. The built-in bus driver drives every byte lane, so the 32-bit configuration is not supported by it.

## Reading order

`basic_demo/verification_top.sv`, `uvm/cg_env.svh`, `common_uvc/common/common_env.svh`, then `uvm/cg_reg_access.svh`
(the common register-write sequence), the two agents (`uvm/register_bus_*`, `uvm/serial_link_*`), the sequences, the
scoreboard and the `tests/basic_demo.svh` test. `basic_demo/files.f` lists the compile order relative to that directory;
it is a source inventory, not a standalone simulation command (UVM, the UART RTL and the define are also required).
DUT RTL, third-party UVM sources, credentials, caches, binaries and run logs are deliberately excluded.

## Reproduce

```sh
DV_AGENT_TEST_SIMULATION=1 .venv/bin/python -m pytest -q tests/test_demo_script.py -k real_uart
```

The sources are copied unchanged from the generated output. Generator changes are separate commits.
