# Partial run: 8-bit UART, quick testing (review copy)

This is what the latest model-driven `/code` run generated. It is **partial and has never been compiled or simulated**.
Nothing in the generator imports this folder. Delete it, or revert its commit, when review is done.

- Run: `orch-20261101T140654Z-quick-testing-2026-11-01T1423204743620000`
- Request: 8-bit UART, resolved to `DATA_BUS_WIDTH_8`
- Result: `BLOCKED` at feature `t_overrun_burst` on 257 facts against a limit of 256 (`code_result.json`). `t_traffic_err` never ran.
- Stages not reached: collation, integration, review, hooks, final render, compile, `/run`.

## What is here

| Folder | Contents | State |
|---|---|---|
| `plan/` | The test plan (`.md`, `.html`, `.json`), the extracted interface, the spec/RTL port comparison | Complete, limited to the 8-bit build |
| `sv/` | SystemVerilog: clock, reset and common UVCs, plus an interface, config, agent, monitor and (where active) driver and sequencer for each of 4 interfaces | Generated, not compiled |
| `interfaces_design/` | The decisions behind each interface: needs assessment, pseudocode, agent and tie-offs | Complete |
| `features/` | For 23 of 25 features: `.md` and pseudocode, plus `.fragment.json`, the typed design | Designs only |
| `execution_plan.json`, `DEPENDENCIES.md` | Step status and feature ordering | |

**There is no SystemVerilog for the features.** Sequences, checks, scoreboard routes and coverage exist only as typed records in
`features/*.fragment.json`; they become SV at the final render, which this run did not reach. There is also no environment,
package, test or top module, so `sv/` cannot be compiled as a project.

## Size of the feature designs

44 sequences, 28 checks, 22 coverage goals, 9 hooks, 7 scoreboard routes, 5 registers. A further **78 items were deferred** because
they did not fit the contract. Each deferral is in the `questions` of its fragment, with the rule it broke. Much of the deferred
work is bus-only checks and coverage written for non-bus agents.

## Reading order

1. `plan/testplan_doc.html`: the plan. Its top lists what is outside the 8-bit build.
2. `interfaces_design/collateral_wishbone_bus.md`, then `sv/wishbone_bus/uvm/`: the built-in bus, with `wb_sel_i` held at 0.
3. `sv/common/`: the common agent and environment.
4. `features/t_wb_seq.md` with `features/t_wb_seq.fragment.json`: one feature, from pseudocode to typed design.

## Limits

- Everything is `NEEDS_REVIEW`. Quick-testing approvals are model inferences, not human approval or design sign-off.
- The run predates commit `8065c06` (fact reuse and the prototype pass rule), so features are not marked `DEFERRED` here and facts are duplicated.
- Files are copied unchanged. The plan's JSON and HTML name local paths from the machine that generated them.
