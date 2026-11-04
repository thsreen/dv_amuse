# Review pack: 8-bit UART16550, passing run

Run `orch-20261104T145239Z`, request "Generate verification collateral for 8 bit UART", define `DATA_BUS_WIDTH_8`.
Code project `a7836a4101734528`. Generated under quick testing: **test-only, NEEDS_REVIEW, not design sign-off.**

## Result

| Check | Result |
|---|---|
| Test plan | 13 of 13 sections |
| Compile (Xezim 0.11.3, Accellera UVM 2020.3.1) | PASS |
| `quick_basic`, seed 1 | PASS |
| Scoreboard comparisons | 2 (one transmit, one receive) |
| UVM errors, fatals, warnings | 0, 0, 61 |
| Assertions and activation covers | 15 of 15 |
| Plan coverage groups | 17: simple average 31.4%, 1 at 100%, 6 with no samples |
| Simulated time | 17.29 us at a 10 ns clock |

The test runs the model's bus setup writes, writes `0x5A` to address 0 for transmit, sends `0xA5` in on the serial line and reads it back at address 0.

## What this does not show

- **It is one script-chosen test, not verification of the UART.** `quick_basic` was chosen by a script because the model's own tests do not yet pass together.
- **The data address and its condition are inferred** from the model's routes, because this run declared no receive route.
- **Approvals are test-only.** Inferred plan items and port and reset decisions were approved by a model evaluator, not by a designer. See `design/reviews/`.
- **Left out of this build:** 9 of 26 features and 80 items are deferred; 2 model tests, 4 model routes, 1 register at the data address and 10 hooks are set aside. See `design/quick_basic_set_aside.json`.
- **Model monitor hooks:** without them the modem and interrupt agents use template defaults, so their coverage is empty. In separate one-hook runs, 3 of them stopped the simulation finishing and 1 raised errors; the cause is not established. Their code is in `design/set_aside_hooks/`. One further scoreboard hook has no saved code.
- **Open items:** 293 questions and 51 review objections from 15 review batches were recorded and did not stop the build. Read them before relying on any expectation.
- **Coverage figures** are the testbench's own reports from this one test. The average is a plain mean.
- **Only the 8-bit build is exercised.** The built-in bus driver does not support 32-bit byte lanes.
- **The waveform was not inspected automatically.** The pass comes from the scoreboard and assertions.

## Where to look

| Path | Contents |
|---|---|
| `test_plan/` | The plan the build used, as HTML, Markdown and JSON. Start with the HTML. |
| `testbench/` | The generated SV and UVM (110 files, matching the build manifest), `code_plan.json`, `code_questions.json`, `traceability.json` |
| `results/` | `run.json`, `coverage_report.md`, `coverage.json`, `quick_basic.fst`, `compile_result.json` |
| `logs/` | `simulation.log`, `compile.log`, `plan_trace.jsonl`, and `code_trace.jsonl`, which includes this run's earlier failed attempts |
| `design/` | Port comparison and audit, review objections, test-only approvals, what was set aside, and per-feature pseudocode and designs in `feature_work/` |

Suggested order: this file, `test_plan/testplan_doc.html`, `results/coverage_report.md`, `testbench/sequences/quick_basic_*.svh`, `testbench/uvm/cg_scoreboard.svh`, `logs/simulation.log`.

## Reproduce

The UART16550 RTL is not included (LGPL 2.1 or later). With Xezim, a UVM source tree and that RTL:

```sh
XEZIM=/path/xezim UVM_SRC=/path/uvm/src UART_RTL=/path/uart16550/rtl/verilog sh reproduce.sh
```

It should report 2 comparisons, `FUNCTIONAL_TEST_PASS quick_basic` and 0 UVM errors. To view the waveform, open the FST in GTKWave or Surfer and add these signals under `verification_top` then `dut`: `wb_adr_i`, `wb_dat_i`, `wb_dat_o`, `wb_we_i`, `wb_stb_i`, `wb_ack_o`, `stx_pad_o`, `srx_pad_i`.

## Notes

Some JSON and HTML files name paths from the build machine, such as `/proj/work/...`, and are left unchanged so their hashes hold. The plan and logs quote the UART specification. `SHA256SUMS` lists every file in this folder.
