# Demo testbench (`/code demo`)

A simulation that compiles, applies reset, drives and runs, with **no model call** and **no DUT behaviour checked**.
Use it for a quick demo when the full code stage is blocked or too slow. It is not verification.

```text
/code demo                                   # the 2 interfaces with the fewest wires; then /run
/code demo 1                                 # just one (a prototype needs one that drives the DUT, so an output-only one gets the next added)
/code demo all                               # every interface, as before
dv-agent build-code --demo [--max-interfaces N] --testplan ... --interface ... --rtl-file ... --top ... --out ... [--compile]
```

## What it builds (`codegen/demo_contract.py`)

- **Clock and reset:** the common UVCs, bound by `common_binding`. If a decision is still open (for example the
  clock is named `wb_clk_i` but the specification says `CLK`), the reviewed spec/RTL port mapping is used, then a
  name hint. Every such guess is written into the contract's `questions`.
- **Every other interface:** one agent per plan interface group (leftover ports share one `misc` group), with a
  generic driver that holds its DUT inputs at zero and a passive monitor. Groups with only DUT outputs are passive.
- **One test:** idle sequences for 64 cycles, then the normal completion marker.
- **Nothing else:** no scoreboards, registers, routes, checks or coverage. `minimum_comparisons` is 0, and the
  simulator does not demand functional-coverage or scoreboard evidence from a `demo` contract.

## Building only some interfaces (prototype first)

`/code demo [N|all]` builds the N interfaces with the fewest wires (default 2; ports, then bits). Every other
interface is **pending**: its inputs are held at 0 in the testbench top, its outputs are left open, and it is listed
at the end of the command output and in `demo_pending.json` (and in the contract's questions). If the chosen interfaces
drive nothing, the next smallest one that does is added so the simulation has stimulus. Check the simulation with
`/run`, then type `/code` to build everything. Verified with the real Xezim + UVM run on the UART fixture: two interfaces
built, the bus and modem interfaces tied off and pending, compile PASS, run PASS
(`DV_AGENT_TEST_SIMULATION=1 pytest tests/test_demo_contract.py -k two_interfaces`).

## Why it exists

The run that prompted it did not fail for lack of interfaces. All eight Wishbone ports were in the JSON. It failed in
the interface-base model step: the model cited facts whose quotes were outside the excerpts it was shown, twice, and
the proof gate refused them ("Fact quote must occur in a retrieved source excerpt"). A demo needs none of that proof.

## Limits

- Reset polarity falls back to the signal's name (`*_n` is low) when the specification does not state it. If it is
  wrong the DUT stays in reset; the simulation still runs.
- Everything built is marked `demo` and `BUILT_NEEDS_REVIEW`. Do not report a demo PASS as functional verification.
- Verified: UART compiles and passes under Xezim with UVM 2020.3.1 using the reviewed port mapping of a real run
  (compile PASS, run PASS), and the UART acceptance fixture passes the same way
  (`DV_AGENT_TEST_SIMULATION=1 pytest tests/test_demo_contract.py -k real_uart`).
