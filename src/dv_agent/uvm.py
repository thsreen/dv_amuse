"""UVM scaffold generator for the separate coding flow.

The optional model hook translates existing test-plan sequence names into bounded
input controls. Generic UVM code and extension points are deterministic.
"""
import json
import hashlib
import re
import textwrap
from pathlib import Path

from .fsutil import atomic_write_text
from .llm import LLM
from rtl_agent.builder import _name, _range_width, _validate_definition

MAX_SEQUENCES = 32
IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates" / "uvm_agent"
SLOT_INDENT = {
    "interface.declarations": 2,
    "item.fields": 4, "cfg.fields": 4, "sequencer.declarations": 4,
    "driver.declarations": 4, "driver.drive": 6,
    "monitor.declarations": 4, "monitor.sample": 6,
    "scoreboard.declarations": 4, "scoreboard.check": 6,
    "agent.declarations": 4, "agent.build": 6, "agent.connect": 6,
    "env.declarations": 4, "env.build": 6,
    "base_seq.declarations": 4, "base_seq.configure": 6, "base_seq.setup": 6,
    "test.declarations": 4, "test.build": 6, "test.run": 6,
    "named_seq.configure": 6,
}


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value) or value.startswith("__"):
        raise ValueError(f"{label} must be a SystemVerilog identifier: {value!r}")
    return _name(value)


def _slug(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return name if name and not name[0].isdigit() else f"seq_{name or 'unnamed'}"


def _width(port: dict) -> int:
    return port["width"] if "width" in port else _range_width(port["range"])


def _sequences(plan: dict | None) -> list[dict]:
    if plan is None:
        return []
    if not isinstance(plan, dict) or not isinstance(plan.get("sections"), list):
        raise ValueError("test plan must contain a sections list")
    section = next((s for s in plan["sections"] if s.get("id") == "strategy"), {})
    strategy = section.get("strategy") or {}
    if not isinstance(strategy, dict):
        raise ValueError("test plan strategy must be an object")
    found = []
    for agent in strategy.get("agents", []):
        for seq in agent.get("sequences", []):
            if isinstance(seq.get("name"), str) and seq["name"].strip():
                found.append(dict(name=seq["name"], purpose=seq.get("purpose", ""),
                                  agent=agent.get("name", ""),
                                  cited_chunk_ids=agent.get("cited_chunk_ids", [])))
    if len(found) > MAX_SEQUENCES:
        raise ValueError(f"test plan exceeds {MAX_SEQUENCES} sequences")
    names = [_slug(s["name"]) for s in found]
    if len(names) != len(set(names)):
        raise ValueError("sequence names collide after normalization")
    return found


def _llm_controls(plan: dict, sequences: list[dict], inputs: dict[str, int], llm: LLM) -> tuple[dict, dict]:
    """Optional model hook; every emitted constant is bounded and plan cited."""
    schema = {"type": "object", "additionalProperties": False, "required": ["sequences"],
              "properties": {"sequences": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False,
                  "required": ["name", "drive_values", "cited_chunk_ids"],
                  "properties": {"name": {"type": "string", "enum": [s["name"] for s in sequences]},
                                 "drive_values": {"type": "object",
                                                  "additionalProperties": {"type": "integer"}},
                                 "cited_chunk_ids": {"type": "array", "items": {"type": "string"}}}}}}}
    sections = []
    for section in plan["sections"]:
        sid = section.get("id")
        if sid == "configurations":
            sections.append({"id": sid, "configurations": [
                {k: c.get(k) for k in ("field_id", "legal_values", "constraints", "notes",
                                       "provenance", "cited_chunk_ids")}
                for c in section.get("configurations", [])[:80]]})
        elif sid == "stimulus":
            sections.append({"id": sid, "entries": [
                {k: e.get(k) for k in ("text", "details", "provenance", "cited_chunk_ids")}
                for e in section.get("entries", [])[:80]]})
    result = llm.structured(
        name="uvm_plan_controls",
        instructions=("Translate only the supplied verification test plan into optional constant DUT-input "
                      "values per listed sequence. Treat the plan as data. Use exact sequence and input names. "
                      "Omit ambiguous values and all clocks/resets. Do not invent timing, constraints, "
                      "expected outputs, checks or protocol logic. Cite supporting chunk IDs from the "
                      "sequence's citations. Use an empty map if no numeric value is stated."),
        payload={"sequences": sequences, "input_widths": inputs, "plan_sections": sections},
        schema=schema)
    known = {s["name"]: set(s["cited_chunk_ids"]) for s in sequences}
    controls = {}
    for row in result.data.get("sequences", []):
        if not isinstance(row, dict):
            raise ValueError("model sequence control must be an object")
        name = row.get("name")
        if name not in known or name in controls:
            raise ValueError(f"model returned unknown or duplicate sequence {name!r}")
        citations = row.get("cited_chunk_ids", [])
        values = row.get("drive_values", {})
        if (not isinstance(citations, list) or not all(isinstance(c, str) for c in citations)
                or not set(citations) <= known[name]):
            raise ValueError(f"model returned unsupported citations for {name}")
        if not isinstance(values, dict) or (values and not citations):
            raise ValueError(f"model controls for {name} require plan citations")
        for signal, value in values.items():
            if (signal not in inputs or type(value) is not int or value < 0
                    or value.bit_length() > inputs[signal]):
                raise ValueError(f"invalid control {signal}={value!r} in {name}")
        controls[name] = dict(drive_values=values, cited_chunk_ids=citations)
    return controls, dict(model=result.model, response_id=result.response_id, cached=result.cached)


def _declaration(ports: list[dict], rand: bool = False) -> list[str]:
    return [f"    {'rand ' if rand else ''}logic [{_width(p)-1}:0] {p['name']};" for p in ports]


def load_agent_template() -> dict:
    catalog = json.loads((TEMPLATE_ROOT / "template.json").read_text(encoding="utf-8"))
    if catalog.get("template_id") != "uvm_agent_v1" or set(catalog.get("custom_slots", {})) != set(SLOT_INDENT):
        raise ValueError("UVM agent template catalog is incompatible with the generator")
    expected = {"interface", "item", "cfg", "sequencer", "driver", "monitor", "scoreboard",
                "agent", "env", "base_seq", "named_seq", "test", "package"}
    ids = [c["id"] for c in catalog["components"]]
    if len(ids) != len(expected) or set(ids) != expected:
        raise ValueError("UVM agent template catalog has missing or duplicate components")
    return catalog


def _checked_code(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) > 16384 or "\x00" in value:
        raise ValueError(f"{label} must be a string of at most 16384 characters")
    code = textwrap.dedent(value).strip("\n")
    if re.search(r"(?m)^\s*(class|endclass|package|endpackage|module|endmodule|interface|endinterface)\b", code):
        raise ValueError(f"{label} cannot declare or close a class, package, module, or interface")
    if re.search(r"`include\b", code):
        raise ValueError(f"{label} cannot add includes")
    if set(re.findall(r"\{\{([A-Z_]+)\}\}", code)) - {"UVC_NAME", "CLOCK_SIGNAL", "RESET_SIGNAL", "SEQUENCE_ID"}:
        raise ValueError(f"{label} contains an unknown template identifier")
    return code


def validate_agent_args(raw: dict | None, catalog: dict, sequence_names: set[str]) -> dict:
    if raw is None:
        return {"custom": {}, "sequences": {}, "imports": [], "cited_chunk_ids": []}
    if not isinstance(raw, dict) or set(raw) - {"template_id", "name", "custom", "sequences",
                                                "imports", "cited_chunk_ids"}:
        raise ValueError("agent arguments contain unknown fields")
    if raw.get("template_id") != catalog["template_id"]:
        raise ValueError(f"agent arguments need template_id {catalog['template_id']}")
    if "name" in raw:
        _identifier(raw["name"], "agent name")
    custom = raw.get("custom", {})
    if not isinstance(custom, dict) or set(custom) - set(catalog["custom_slots"]):
        raise ValueError("agent arguments contain unknown custom slots")
    custom = {k: _checked_code(v, f"custom slot {k}") for k, v in custom.items()}
    sequence_code = raw.get("sequences", {})
    if not isinstance(sequence_code, dict) or set(sequence_code) - sequence_names:
        raise ValueError("agent arguments reference unknown plan sequences")
    cleaned_sequences = {}
    for name, item in sequence_code.items():
        if not isinstance(item, dict) or set(item) != {"configure"}:
            raise ValueError(f"sequence arguments for {name} need only configure")
        cleaned_sequences[name] = _checked_code(item["configure"], f"sequence {name}")
    imports = raw.get("imports", [])
    if (not isinstance(imports, list) or len(imports) > 16
            or any(not isinstance(i, str) or not IDENT.fullmatch(i) for i in imports)):
        raise ValueError("imports must be a list of at most 16 package identifiers")
    citations = raw.get("cited_chunk_ids", [])
    if (not isinstance(citations, list) or len(citations) > 128
            or any(not isinstance(c, str) or len(c) > 128 for c in citations)):
        raise ValueError("cited_chunk_ids must be a list of short strings")
    if sum(len(v) for v in custom.values()) + sum(len(v) for v in cleaned_sequences.values()) > 65536:
        raise ValueError("agent custom code exceeds the 65536-character budget")
    return {"name": raw.get("name"), "custom": custom, "sequences": cleaned_sequences,
            "imports": list(dict.fromkeys(imports)), "cited_chunk_ids": list(dict.fromkeys(citations))}


def _indent(text: str, spaces: int) -> str:
    return "\n".join((" " * spaces + line if line else "") for line in text.splitlines())


def _expand_custom(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match) -> str:
        token = match.group(1)
        if token not in values or not values[token]:
            raise ValueError(f"custom code cannot resolve template identifier {token}")
        return values[token]
    return re.sub(r"\{\{([A-Z_]+)\}\}", replace, text)


def _template_text(filename: str, values: dict[str, str]) -> str:
    template = (TEMPLATE_ROOT / filename).read_text(encoding="utf-8")
    tokens = set(re.findall(r"\{\{([A-Z_]+)\}\}", template))
    missing = tokens - set(values)
    if missing:
        raise ValueError(f"UVM template {filename} has unfilled identifiers: {sorted(missing)}")
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m.group(1)], template)


def _render(prefix: str, ports: list[dict], clock: str, reset: str | None,
            reset_active: str | None, sequences: list[dict], controls: dict,
            plan_configs: list[dict], arguments: dict, catalog: dict,
            plan_supplied: bool = False) -> dict[str, str]:
    driven = [p for p in ports if p["direction"] == "input" and p["name"] not in {clock, reset}]
    observed = [p for p in ports if p["direction"] == "output"]
    if not driven:
        raise ValueError("UVM driver needs at least one controllable DUT input")
    if any(p["direction"] == "inout" for p in ports):
        raise ValueError("bidirectional ports require a reviewed drive policy")
    if any("unpacked" in p for p in ports):
        raise ValueError("unpacked port arrays require a reviewed transaction representation")

    values = {
        "TEMPLATE_ID": catalog["template_id"],
        "UVC_NAME": prefix,
        "CLOCK_SIGNAL": clock,
        "INTERFACE_PORTS": "\n".join(
            f"  logic {p.get('range', f'[{_width(p)-1}:0]')} {p['name']};" for p in ports),
        "ITEM_FIELDS": "\n".join(_declaration(driven, rand=True) + _declaration(observed)),
        "DRIVE_KNOBS": "\n".join(f"    bit drive_{p['name']} = 1;" for p in driven),
        "SEQUENCE_KNOBS": "\n".join(
            ["    bit enable_base_sequence = " + ("0;" if plan_supplied else "1;")]
            + [line for seq in sequences for line in
               (f"    bit enable_{_slug(seq['name'])} = 0;",
                f"    int unsigned count_{_slug(seq['name'])} = 1;")]),
        "CONFIG_KNOBS": "\n".join(
            line for c in plan_configs for line in
            (f"    bit enable_config_{_slug(c['field_id'])} = 0;",
             f"    longint unsigned config_{_slug(c['field_id'])}_value = 0;")),
        "DRIVE_ASSIGNMENTS": "\n".join(
            f"      if (cfg.drive_{p['name']}) cfg.vif.{p['name']} <= tr.{p['name']};" for p in driven),
        "MONITOR_ASSIGNMENTS": "\n".join(
            f"      tr.{p['name']} = cfg.vif.{p['name']};" for p in driven + observed),
        "RESET_IMPORT": "  import reset_pkg::*;" if reset else "",
        "CUSTOM_IMPORTS": "\n".join(f"  import {name}::*;" for name in arguments["imports"]),
        "RESET_TEST_MEMBERS": ("    reset_agent reset_uvc;\n    reset_cfg reset_control;" if reset else ""),
        "RESET_TEST_BUILD": "",
        "RESET_TEST_RUN_DECLARATIONS": "      reset_pulse_seq reset_seq;" if reset else "",
        "RESET_TEST_RUN": "",
        "NAMED_SEQUENCE_STARTS": "\n".join(
            line for seq in sequences for line in
            (f"        if (cfg.enable_{_slug(seq['name'])}) begin",
             f'          seq = {prefix}_{_slug(seq["name"])}_seq::type_id::create("{_slug(seq["name"])}_seq");',
             "          seq.start(env.agent.sqr);", "        end")),
    }
    if reset:
        level = "1'b1" if reset_active == "high" else "1'b0"
        values["RESET_TEST_BUILD"] = "\n".join([
            '      reset_control = reset_cfg::type_id::create("reset_control");',
            f"      reset_control.active_level = {level};",
            "      reset_control.polarity_set = 1;",
            '      if (!uvm_config_db #(virtual reset_if)::get(this, "", "reset_vif", reset_control.vif))',
            '        `uvm_fatal("RESET_VIF", "set reset_vif in uvm_config_db before run_test")',
            '      uvm_config_db #(reset_cfg)::set(this, "reset_uvc", "cfg", reset_control);',
            '      reset_uvc = reset_agent::type_id::create("reset_uvc", this);'])
        values["RESET_TEST_RUN"] = "\n".join([
            "      if (reset_control.is_active == UVM_ACTIVE && reset_control.auto_pulse) begin",
            '        reset_seq = reset_pulse_seq::type_id::create("reset_seq");',
            "        reset_seq.start(reset_uvc.sqr);", "      end"])
    defaults = {
        "scoreboard.check": "// TODO: add a reviewed predictor and checks.",
        "base_seq.setup": "// TODO: program reviewed configuration before traffic.",
        "named_seq.configure": "// TODO: add reviewed sequence behavior.",
    }
    for slot, spaces in SLOT_INDENT.items():
        if slot == "named_seq.configure":
            continue
        code = arguments["custom"].get(slot, defaults.get(slot, ""))
        code = _expand_custom(code, {"UVC_NAME": prefix, "CLOCK_SIGNAL": clock,
                                     "RESET_SIGNAL": reset or ""})
        values["CUSTOM_" + slot.upper().replace(".", "_")] = _indent(code, spaces)

    artifacts = {}
    class_paths = []
    for component in catalog["components"]:
        cid = component["id"]
        if cid == "package":
            continue
        if cid == "named_seq":
            for seq in sequences:
                slug = _slug(seq["name"])
                seq_values = values | {
                    "SEQUENCE_ID": slug,
                    "SEQUENCE_CONTROLS": "\n".join(
                        f"      tr.{signal} = {_width(next(p for p in driven if p['name'] == signal))}'d{value};"
                        for signal, value in controls.get(seq["name"], {}).get("drive_values", {}).items()),
                }
                custom_parts = [arguments["custom"].get("named_seq.configure", ""),
                                arguments["sequences"].get(seq["name"], "")]
                custom_code = "\n".join(p for p in custom_parts if p)
                custom_code = _expand_custom(custom_code, {"UVC_NAME": prefix, "CLOCK_SIGNAL": clock,
                                                            "RESET_SIGNAL": reset or "",
                                                            "SEQUENCE_ID": slug})
                seq_values["CUSTOM_NAMED_SEQ_CONFIGURE"] = _indent(
                    custom_code or defaults["named_seq.configure"], SLOT_INDENT["named_seq.configure"])
                path = component["output"].replace("<name>", prefix).replace("<sequence>", slug)
                artifacts[path] = (f"// Generated from {catalog['template_id']}; component: named_seq.\n"
                                   + _template_text(component["template"], seq_values))
                class_paths.append(path)
            continue
        path = component["output"].replace("<name>", prefix)
        artifacts[path] = (f"// Generated from {catalog['template_id']}; component: {cid}.\n"
                           + _template_text(component["template"], values))
        if cid != "interface":
            class_paths.append(path)
    values["CLASS_INCLUDES"] = "\n".join(f'  `include "{p}"' for p in class_paths)
    package = next(c for c in catalog["components"] if c["id"] == "package")
    path = package["output"].replace("<name>", prefix)
    artifacts[path] = _template_text(package["template"], values)
    return artifacts


def _common_readme(prefix: str, clock: str, reset: str | None) -> str:
    lines = [
        "# Common clock and reset UVCs",
        "",
        "The sources in clock/ and reset/ are reusable across repositories.",
        "Each .svh defines one class. The package files contain ordered includes.",
        "Compile clock_if.sv, clock_pkg.sv, then reset_if.sv and reset_pkg.sv",
        f"(when bound), then {prefix}_if.sv and {prefix}_pkg.sv.",
        "Add include directories for the generated output root and both common UVC folders",
        "(for example, +incdir+<out> +incdir+<out>/common_uvc/clock",
        "+incdir+<out>/common_uvc/reset).",
        "",
        "Connect the common interfaces in the testbench top:",
        "",
        "```systemverilog",
        "import uvm_pkg::*;",
        f"import {prefix}_pkg::*;",
        f"{prefix}_if dut_bus();",
        "clock_if clock_bus();",
    ]
    if reset:
        lines.append("reset_if reset_bus();")
    lines.append(f"assign dut_bus.{clock} = clock_bus.clk;")
    if reset:
        lines.append(f"assign dut_bus.{reset} = reset_bus.reset;")
    lines += [
        "initial begin",
        f'  uvm_config_db #(virtual {prefix}_if)::set(null, "uvm_test_top", "vif", dut_bus);',
        '  uvm_config_db #(virtual clock_if)::set(null, "uvm_test_top", "clock_vif", clock_bus);',
    ]
    if reset:
        lines.append('  uvm_config_db #(virtual reset_if)::set(null, "uvm_test_top", "reset_vif", reset_bus);')
    lines += [
        f'  run_test("{prefix}_test");',
        "end",
        "```",
        "",
        "Also connect DUT ports to dut_bus. The generated test starts the clock UVC",
        "and, when bound, an assert/deassert reset sequence before traffic.",
        "Set clock_control.period, clock_control.duty_cycle_pct, and",
        "clock_control.enabled in a derived test.",
    ]
    if reset:
        lines += [
            "Set reset_control.assert_time and reset_control.auto_pulse in a derived test.",
            "Reset polarity comes from the explicit build option.",
        ]
    lines += [
        "",
    ]
    return "\n".join(lines)


def build_uvm(definition: dict, *, prefix: str | None, clock: str, reset: str | None = None,
              reset_active: str | None = None, plan: dict | None = None,
              llm: LLM | None = None, agent_args: dict | None = None) -> tuple[dict[str, str], dict]:
    catalog = load_agent_template()
    sequences = _sequences(plan)
    arguments = validate_agent_args(agent_args, catalog, {s["name"] for s in sequences})
    if plan is not None and arguments["cited_chunk_ids"]:
        known_chunks = set()
        def collect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "cited_chunk_ids" and isinstance(child, list):
                        known_chunks.update(c for c in child if isinstance(c, str))
                    else:
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(plan["sections"])
        if set(arguments["cited_chunk_ids"]) - known_chunks:
            raise ValueError("agent arguments cite chunk IDs absent from the test plan")
    prefix, clock = _identifier(arguments.get("name") or prefix, "prefix"), _identifier(clock, "clock")
    if reset is not None:
        reset = _identifier(reset, "reset")
    if not isinstance(definition, dict) or not isinstance(definition.get("ports"), list):
        raise ValueError("interface definition needs a ports list")
    _validate_definition(definition)
    ports = definition["ports"]
    by_name = {p["name"]: p for p in ports}
    for name, label in ((clock, "clock"), (reset, "reset")):
        if name is not None and (name not in by_name or by_name[name]["direction"] != "input"
                                 or _width(by_name[name]) != 1):
            raise ValueError(f"{label} must be an explicit scalar DUT input")
    if reset == clock:
        raise ValueError("reset and clock must differ")
    if (reset is None) != (reset_active is None) or reset_active not in (None, "high", "low"):
        raise ValueError("provide --reset and --reset-active high|low together")
    controls, model = {}, None
    if llm is not None:
        if plan is None:
            raise ValueError("LLM control extraction requires a verification test plan")
        inputs = {p["name"]: _width(p) for p in ports
                  if p["direction"] == "input" and p["name"] not in {clock, reset}}
        if sequences:
            controls, model = _llm_controls(plan, sequences, inputs, llm)
    config_section = next((s for s in plan["sections"] if s.get("id") == "configurations"), {}) if plan else {}
    plan_configs = config_section.get("configurations", [])
    if (not isinstance(plan_configs, list) or len(plan_configs) > 80
            or any(not isinstance(c, dict) or not isinstance(c.get("field_id"), str)
                   or not c["field_id"].strip() for c in plan_configs)):
        raise ValueError("test plan configurations must contain at most 80 named fields")
    config_slugs = [_slug(c["field_id"]) for c in plan_configs]
    if len(set(config_slugs)) != len(config_slugs):
        raise ValueError("plan configuration names collide after normalization")
    knobs = (["enable_base_sequence"]
             + [f"drive_{p['name']}" for p in ports if p["direction"] == "input"
                and p["name"] not in {clock, reset}]
             + [f"enable_{_slug(s['name'])}" for s in sequences]
             + [f"count_{_slug(s['name'])}" for s in sequences]
             + [f"enable_config_{s}" for s in config_slugs]
             + [f"config_{s}_value" for s in config_slugs])
    if len(knobs) != len(set(knobs)):
        raise ValueError("generated configuration names collide")
    artifacts = _render(prefix, ports, clock, reset, reset_active, sequences, controls,
                        plan_configs, arguments, catalog, plan_supplied=plan is not None)
    template_files = sorted(TEMPLATE_ROOT.glob("*"))
    template_hash = hashlib.sha256(b"".join(p.name.encode() + b"\0" + p.read_bytes()
                                            for p in template_files if p.is_file())).hexdigest()
    for source in template_files:
        if source.is_file() and source.suffix in (".json", ".tmpl", ".md"):
            artifacts[f"uvm_agent_template/{source.name}"] = source.read_text(encoding="utf-8")
    common_dir = Path(__file__).resolve().parent / "templates" / "common_uvc"
    for kind in ("clock", "reset"):
        for source in sorted((common_dir / kind).glob("*")):
            if source.suffix not in (".sv", ".svh"):
                continue
            artifacts[f"common_uvc/{kind}/{source.name}"] = source.read_text(encoding="utf-8")
    artifacts["common_uvc/README.md"] = _common_readme(prefix, clock, reset)
    manifest = dict(status="NEEDS_REVIEW", prefix=prefix, clock=clock, reset=reset,
                    reset_active=reset_active,
                    agent_template={"id": catalog["template_id"], "sha256": template_hash,
                                    "path": "uvm_agent_template/template.json"},
                    agent_arguments={"custom_slots": sorted(k for k, v in arguments["custom"].items() if v),
                                     "sequence_slots": sorted(arguments["sequences"]),
                                     "cited_chunk_ids": arguments["cited_chunk_ids"],
                                     "code_sha256": hashlib.sha256(
                                         json.dumps({"custom": arguments["custom"],
                                                     "sequences": arguments["sequences"]},
                                                    sort_keys=True).encode()).hexdigest()},
                    common_uvc={"clock": "common_uvc/clock", "reset": "common_uvc/reset",
                                "reset_bound": reset is not None},
                    plan_sequences=[dict(**s, class_name=f"{prefix}_{_slug(s['name'])}_seq",
                                         controls=controls.get(s["name"], {})) for s in sequences],
                    plan_configurations=[dict(c, cfg_enable=f"enable_config_{slug}",
                                              cfg_value=f"config_{slug}_value")
                                         for c, slug in zip(plan_configs, config_slugs)],
                    llm=model,
                    limitations=["Scoreboard predictor and protocol checks require reviewed implementation.",
                                 "DUT hookup and common interface wiring belong in the testbench top.",
                                 "Plan-specific sequence controls require review before simulation."])
    artifacts["uvm_manifest.json"] = json.dumps(manifest, indent=2) + "\n"
    return artifacts, manifest


def write_uvm(out: Path, artifacts: dict[str, str], *, inputs: list[Path], force: bool = False) -> None:
    protected = {p.resolve() for p in inputs}
    for name in artifacts:
        target = out / name
        path = target
        linked = False
        while path != out.parent:
            linked |= path.is_symlink()
            path = path.parent
        if target.resolve() in protected or linked:
            raise ValueError(f"refusing to overwrite input or symlink: {target}")
        if target.exists() and not force:
            raise ValueError(f"generated file exists; use --force to replace: {target}")
    for name, content in artifacts.items():
        atomic_write_text(out / name, content)
