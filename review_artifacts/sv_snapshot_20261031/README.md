# Temporary SV review snapshot

This directory is a removable review copy. Nothing in the generator imports it. Delete this entire
`review_artifacts/sv_snapshot_20261031/` directory when review is complete, or revert its single commit.

## What to review

- **validated_uart/**: complete generated acceptance example, freshly compiled and simulated under
  Xezim with UVM 2020.3.1. Both `basic_functional` and `random_transmit` passed. Includes reusable
  clock/reset/common UVCs, physical interfaces, agents/drivers/monitors, sequences, checks, monitor-fed
  coverage, scoreboard, derived environment, test classes and top-level wiring.
- **latest_partial/**: clock/reset/common sources actually emitted by the latest user-run work package.
  That run stopped at WISHBONE scaffolding with a retrieved-fact citation error. This is partial output;
  it has no completed testbench and has not been independently simulated as a project.
- **validation.json**: explicit validation scope, configuration and observed test results.

The complete example uses the explicit acceptance fixture, not a successful autonomous `/code` run.
It selects `DATA_BUS_WIDTH_8`. The latest user's selected RTL uses a different bus configuration;
do not transplant this example's configuration/approvals into that run. Passing these two tests is
not functional sign-off or complete UART coverage.

## Reading order

Start with `validated_uart/verification_top.sv`, `uvm/cg_env.svh`,
`common_uvc/common/common_env.svh`, then the agent/sequence/check/coverage/scoreboard files.
`validated_uart/files.f` records generated source compilation order relative to that directory.
It is a source inventory, not a standalone simulation command: external UVM package/includes,
original UART RTL and the stated defines are also required. DUT RTL and third-party UVM sources,
credentials, caches, binaries and temporary run logs are deliberately excluded.

## Reproduce validation

From the dv_agent repository with its baseline RTL and installed simulator/UVM dependencies:

```sh
DV_AGENT_TEST_SIMULATION=1 .venv/bin/python -m pytest -q tests/test_codegen.py -k real_uart
```

The SV sources here are copied unchanged from the generated outputs. Generator source changes
remain separate from this review-only publication.
