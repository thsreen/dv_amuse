# UVM scaffold (separate coding flow)

`build-uvm` generates an extendable UVM package from an explicit
`interface_definition.json`. It does not run during the specification-only
test-plan pipeline and does not inspect design source.

```bash
.venv/bin/dv-agent build-uvm runs/uart_rtl_default/interface_definition.json \
  --out runs/uart_uvm --prefix uart --clock wb_clk_i \
  --reset wb_rst_i --reset-active high
```

The output contains `uart_if.sv`, `uart_pkg.sv`, one class per file under
`uvm/*.svh`, `uvm_manifest.json`, and `common_uvc/clock/` and
`common_uvc/reset/`. The three package files have imports and ordered
`include` directives; they contain no class definitions. Both common UVCs are copied on
every build, including when the selected design has no reset port. Their
SystemVerilog sources are identical across projects. The generated
`common_uvc/README.md` lists the compile order and project-specific wiring.
Compile the common interfaces and packages before the generated interface
and package, with your simulator's UVM library available. Add the output root
and both common UVC directories to the compiler's include path so all
`.svh` files resolve.

The testbench top connects the common interfaces to DUT wiring and sets three
virtual interfaces:

```systemverilog
import uvm_pkg::*;
import uart_pkg::*;
uart_if bus();
clock_if clock_bus();
reset_if reset_bus();
assign bus.wb_clk_i = clock_bus.clk;
assign bus.wb_rst_i = reset_bus.reset;
initial begin
  uvm_config_db #(virtual uart_if)::set(null, "uvm_test_top", "vif", bus);
  uvm_config_db #(virtual clock_if)::set(null, "uvm_test_top", "clock_vif", clock_bus);
  uvm_config_db #(virtual reset_if)::set(null, "uvm_test_top", "reset_vif", reset_bus);
  run_test("uart_test");
end
```

The testbench top must also connect the DUT ports. The generator requires an
explicit clock. A reset is optional, but `--reset` and `--reset-active high|low`
must be supplied together so polarity is never inferred. Clock UVC
`clock_cfg` controls period, duty-cycle percent, enabled state, idle level and
active/passive mode. Reset UVC `reset_cfg` controls polarity, assert duration,
active/passive mode and whether the initial pulse runs. The generated test
starts the clock controller and, when reset is bound, an assert/deassert pulse
before traffic. A derived test can change those settings or start
`reset_pulse_seq` later.

The main agent's driver moves randomized transaction input fields onto
DUT inputs at the falling clock edge; the monitor samples inputs and outputs
at the rising edge. Change these virtual methods for the reviewed protocol.
Bidirectional ports and unpacked arrays are refused until their transaction
representation and drive policy are provided. Packed range syntax is kept in
the generated interface.

The generated `uvm/` directory contains an item, configuration object,
sequencer, driver, monitor, scoreboard, agent, environment, base sequence,
plan-named sequences and test, each in its own file. The configuration
object controls active/passive mode, per-input drive enables, the base
sequence, item count, inter-item cycles, and scoreboard creation. The
scoreboard starts **disabled** because there is no expected-behavior model;
`check_sample` is the extension point for a reviewed predictor and comparisons.
The generated classes have UVM factory registration, so a project can extend
them in a separate package and apply factory overrides. `drive_item`,
`sample_item`, `check_sample`, `configure_item`, `apply_configuration`,
and `item_count` are virtual. `apply_configuration` runs before each sequence's
traffic and is the hook for reviewed register setup.

## Agent template and arguments

The [agent template catalog](../src/dv_agent/templates/uvm_agent/template.json)
lists every generated component, its source template, output path, purpose,
and named customization slots. The generator fills common identifiers
(`{{UVC_NAME}}`, `{{CLOCK_SIGNAL}}`, fields, signal assignments, and includes)
with deterministic code. It copies the catalog and templates into
`uvm_agent_template/` in each output so a later LLM can read the same contract.
Every generated file carries template ID `uvm_agent_v1`.

An optional argument JSON can rename the agent, add package imports, fill
custom slots, and add code to a named plan sequence:

```json
{
  "template_id": "uvm_agent_v1",
  "name": "uart",
  "custom": {
    "driver.declarations": "int unsigned driven_items;",
    "driver.drive": "driven_items++;",
    "scoreboard.check": "// reviewed predictor and comparison code"
  },
  "sequences": {
    "Send Data": {"configure": "tr.valid = 1'b1;"}
  },
  "cited_chunk_ids": ["a supporting plan chunk ID"]
}
```

Pass it with `--agent-args path/to/agent_args.json`. `name` may replace
`--prefix`. Custom snippets may use `{{UVC_NAME}}`, `{{CLOCK_SIGNAL}}`,
`{{RESET_SIGNAL}}`, and for named sequences `{{SEQUENCE_ID}}`. The script
validates slot names, known plan sequences, identifiers and size bounds and
rejects nested class/package declarations. The manifest records filled slots,
citations and hashes. Custom SV remains `NEEDS_REVIEW` until compiled and
checked against the test plan. The built-in `--llm on` hook currently proposes
only bounded constant sequence controls; a later model can produce this
argument JSON without changing the generic generator.

Pass a generated verification plan to add named sequence subclasses:

```bash
.venv/bin/dv-agent build-uvm runs/uart_rtl_default/interface_definition.json \
  --out runs/uart_uvm --prefix uart --clock wb_clk_i \
  --reset wb_rst_i --reset-active high \
  --testplan path/to/testplan_doc.json
```

Each plan sequence has `cfg.enable_<name>` (default 0) and
`cfg.count_<name>` (default 1). The generated test starts only enabled
sequences. When a plan is supplied, the base sequence is disabled by default.
Set these fields in a derived test or a factory override before run phase.
Sequence names, purposes, plan chunk IDs, and the plan's configuration entries
are recorded in `uvm_manifest.json`. Register programming and legal value
constraints require reviewed implementation. Each plan field also gets a
disabled `cfg.enable_config_<field>` and a `cfg.config_<field>_value` knob.
The manifest maps original field IDs to those names. The generator does not
guess how a register field maps to bus transactions.

With `--llm on`, the only model call translates the supplied plan's strategy,
configuration, and stimulus sections into optional constant DUT-input values
for named sequences. It sees port names/widths, not RTL. Every emitted value
must name a controllable input, fit its width, and carry a chunk ID already
cited by that plan sequence. The model response ID and controls are recorded
in the manifest, which remains `NEEDS_REVIEW`. No model call writes scoreboard
predictions or protocol timing. Ordinary builds are offline (`--llm off`).

Existing output files are protected unless `--force` is supplied. Keep custom
subclasses in separate files so regeneration does not overwrite them.
Compilation and simulation are separate verification steps; this generator
does not claim either has passed.
