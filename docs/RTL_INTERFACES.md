# RTL interface JSON

Implementation: `src/rtl_agent/`, a standalone Python package with its own interface templates.
Use `.venv/bin/python -m rtl_agent`; installing this project also provides the `rtl-agent` entry point.
The existing `dv-agent rtl-interfaces` / `build-interface` commands forward to the same package.

The template is [`rtl_interface_v0.json`](../src/rtl_agent/templates/rtl_interface_v0.json).
The definition is a small wiring inventory:

```json
{
  "sources": ["uart_top.v"],
  "direction_reference": "DUT",
  "parameters": [
    {"name": "UART_DATA_WIDTH"   , "width": 32},
    {"name": "UART_ADDR_WIDTH"   , "width": 5}
  ],
  "ports": [
    {"direction": "input"    , "width": 1    , "name": "wb_clk_i"},
    {"direction": "input"    , "width": 32   , "name": "wb_dat_i"},
    {"direction": "output"   , "width": 32   , "name": "wb_dat_o"}
  ]
}
```

The example shows a subset of the ports. The extractor writes all active ports.
Port fields are ordered as direction, width/range, name, optional description. Padding is before commas; exactly one space follows each comma.

- `sources` contains only the selected top file's basename; includes are read to resolve declarations.
- All directions are relative to the DUT: `input`, `output`, or `inout`.
- Parameter names are capitalized in JSON; original RTL names remain unchanged. Parameter `width`
  holds the resolved numeric setting (for example, data width 32).
- Use `width` by default, for example `"width": 8`. The equivalent `"range": "[7:0]"` is
  supported as an alternative. Ascending, nonzero and multidimensional indexing retains ranges;
  unpacked arrays use bracket notation in `unpacked`.
- `description` is optional text and is the last column when supplied. It is preserved when building
  saved JSON; extraction does not invent descriptions. There is no `comment` field.
- The [commented reference template](../src/rtl_agent/templates/rtl_interface_reference.jsonc) shows
  the alternative range row directly below its width row. Comments are confined to this `.jsonc`
  guide; generated `.json` files and the basic runtime template remain standard JSON.
- Signedness, data types, source quotations/hashes, configuration, status and review metadata are omitted.
  Signedness is unnecessary for wiring but matters for later arithmetic interpretation.

## Use

From `dv_agent/`:

```bash
.venv/bin/python -m rtl_agent rtl-interfaces ../baseline_repos/uart16550/rtl/verilog/uart_top.v \
  --top uart_top --out runs/uart_rtl_default --build
```

Writes the compact `rtl_interfaces.json` and `interface_definition.json`. Without `--build`, only
`rtl_interfaces.json` is written. To build from that saved JSON:

```bash
.venv/bin/python -m rtl_agent build-interface runs/uart_rtl_default/rtl_interfaces.json \
  --out runs/uart_rtl_default
```

`-I`, `-D` and `-P` select include directories, defines and original RTL parameter overrides at
extraction time. Run extraction again to reflect source or configuration changes; the saved JSON is
an inventory, not a source cache.

Optional `--groups groups.json` supplies an object mapping group names to signal-name lists.
Every signal must occur exactly once. No default group or inferred protocol/timing fields are added.

Optional SV export remains available directly from original RTL with `--build --emit-sv`.
The compact saved JSON omits the details needed for faithful SV export; `build-interface` from
compact JSON builds JSON only. Explicit clocking options apply only to the original-RTL export.

## Boundaries

This is an offline declaration extractor, isolated from the specification-only test-plan pipeline.
It supports ANSI/non-ANSI ports, fixed arrays, integer parameters, object macros, includes and
conditional declarations. Unsupported selected types/expressions fail explicitly; behavioral HDL is
not elaborated. Existing bounded-parser resource limits remain in place. No original RTL is modified.

The legacy `old_reference/silicon-copilot` port inventory inspired the fields. The local default,
8-bit-plus-baud, and baud-only UART variants were checked against it (19, 20, 20 ports respectively).
Generated SV compilation/simulation and live API integration remain NOT_RUN.
