# Common clock and reset: step-by-step flow

Every testbench needs a clock and a reset, and the specification says little about them beyond which input
is which. The generated testbench therefore reuses fixed UVC library sources and needs only a **binding**: the clock
port, the reset port and its active level. No model call is involved.

## Why the old flow failed

Clock and reset were two model-driven units. Each request carried retrieved evidence, repair feedback and a
copy of every earlier clarification, and each answer was checked against quotes. In the run that failed, the
model asked for confirmation of an answer it had already been given, six times. Every approval added another
clarification section to the plan, and the next request retrieved that section as evidence: the payload grew by
about 5 KB per round (11 KB to 45 KB) until it crossed the 48,000-character limit and the run stopped with
"work package too large". The facts it cited also failed the quote check in several rounds, which triggered
repairs that added still more text.

## The steps (`codegen/common_binding.py`)

| # | Step | Input | Output | Decision needed from a person? |
|---|---|---|---|---|
| 1 | **Inventory** | Interface JSON ports; the plan's interface groups | Scalar DUT inputs; testbench-supplied clock and reset groups (computed role, not model output) | never |
| 2 | **Clock** | The clock group and the port names | The clock port | only if no port name matches exactly, or several clocks exist |
| 3 | **Reset** | The reset group, port names and its documented active level | The reset port and `high` or `low` | only if the port is ambiguous or the active level is not documented |
| 4 | **Timing** | Recorded decisions, if any | Period (default 10 ns), reset duration (default 8 cycles), approved bands (none unless decided) | never; these are testbench settings, not DUT limits |
| 5 | **Copy** | `src/dv_agent/uvc/{clock,reset,common}` (fixed source, not templates) | Files copied unchanged into `units/` and the project's `common_uvc/` | never |
| 6 | **Validate** | Bindings, facts, plan | Scalar inputs, clock differs from reset, every binding cites a documented plan item or a recorded decision | never |

A missing decision becomes **one question** that names the affected port and lists the candidate ports. Its
input is a single source quote, so it does not grow. Once answered, the answer is stored in the plan and read
back; it is never asked again. The dashboard shows two steps for this: *Clock and reset: bind* and *Common UVC*.

## What is copied from the UVC library

These are fixed SystemVerilog sources with no placeholders. They are copied unchanged; a project changes their
behavior only through the configuration objects and UVM factory overrides.

```
src/dv_agent/uvc/
  clock/    clock_if, clock_cfg, clock_driver, clock_monitor, clock_agent, clock_tick, clock_pkg
  reset/    reset_if, reset_cfg, reset_item, reset_sequencer, reset_driver, reset_monitor, reset_agent,
            reset_pulse_seq, reset_pkg
  common/   common_cfg   holds clock_cfg and reset_cfg; bind_clock() and bind_reset() are the only
                         project-specific calls
            common_agent instantiates clock_agent and reset_agent, gives each its own cfg, apply_reset()
            common_env   instantiates common_agent from a common_cfg
            common_pkg   imports clock_pkg and reset_pkg and includes the three classes
```

The generated test builds one `common_cfg`, binds the clock and reset interfaces, creates `common_env`, and
calls `common_infra.agent.apply_reset()`. The top module connects `clock_bus.clk` and `reset_bus.reset` to the
bound DUT ports. Compile order: `clock_if`, `reset_if`, `clock_pkg`, `reset_pkg`, `common_pkg`, then the
design's interfaces and package.

## Extending it later

Custom UVCs that a testplan needs can be added to `common_agent` (or siblings in `common_env`) without touching
a test: add the UVC under `src/dv_agent/uvc/` (and to `COMMON_UVCS` in `uvc/__init__.py`), create it in `common_agent.build_phase` with its own cfg
object, and include its package from `common_pkg`. The binding step grows by one step per UVC, each with a small
fixed input.

## Limits

- Clock operating bands are no longer extracted by a model. They exist only when a person (or an isolated
  quick-testing run) approves them, so the plan still asks for them in "Questions to Designers".
- Mapping a specification name such as `CLK` to a port such as `wb_clk_i` is not guessed from the name. It
  is asked once.
- Verified: the UART acceptance project compiles and passes both tests under Xezim with UVM 2020.3.1
  (`DV_AGENT_TEST_SIMULATION=1 pytest tests/test_codegen.py -k real_uart`).
