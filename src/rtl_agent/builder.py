"""Render configured port contracts into reviewable SystemVerilog interface artifacts."""
import json
import math
import re
from pathlib import Path

from .fsutil import atomic_write_text
from .source import IDENT, RESERVED, RTLExtractionError


def _range_text(dimensions: list[dict], left: str = "left", right: str = "right") -> str:
    return "".join(f"[{d[left]}:{d[right]}]" for d in dimensions)


def _range_width(value: str) -> int:
    if (not isinstance(value, str) or len(value) > 1024
            or re.fullmatch(r"(?:\[-?\d+:-?\d+\])+", value) is None):
        raise RTLExtractionError(f"invalid range: {value!r}; expected [7:0]")
    bounds = [(int(a), int(b)) for a, b in re.findall(r"\[(-?\d+):(-?\d+)\]", value)]
    if any(abs(v) >= 2 ** 31 for pair in bounds for v in pair):
        raise RTLExtractionError("range bounds exceed the supported integer range")
    width = math.prod(abs(a - b) + 1 for a, b in bounds)
    if width > 1_048_576:
        raise RTLExtractionError("range exceeds the 1048576-bit port budget")
    return width


def interface_definition(contract: dict, *, groups: dict | None = None) -> dict:
    """Project parser details into the small user-facing wiring definition."""
    template = Path(__file__).resolve().parent / "templates" / "rtl_interface_v0.json"
    definition = json.loads(template.read_text(encoding="utf-8"))
    detailed = "top_source" in contract
    sources = [contract["top_source"]] if detailed else contract["sources"]
    definition["sources"] = [Path(s).name for s in sources]
    definition["parameters"] = [dict(name=p["name"].upper(), width=p["value"] if detailed else p["width"])
                                for p in contract["parameters"]]
    # Only when set, so an unconfigured interface keeps its format. The compile step needs the same configuration.
    configured = (contract.get("configuration") or {}).get("defines") if detailed else contract.get("defines")
    if configured:
        definition["defines"] = (sorted(k if v == "1" else f"{k}={v}" for k, v in configured.items())
                                 if isinstance(configured, dict) else list(configured))
    parameter_names = [p["name"] for p in definition["parameters"]]
    if len(parameter_names) != len(set(parameter_names)):
        raise RTLExtractionError("parameter names collide after capitalization")
    for p in contract["ports"]:
        port = dict(direction=p["direction"])
        if detailed:
            packed = p["packed_dimensions"]
            if not packed or (len(packed) == 1 and packed[0]["right"] == 0 and packed[0]["left"] >= 0):
                port["width"] = p["width_bits"]
            else:
                port["range"] = _range_text(packed)
            if p["unpacked_dimensions"]:
                port["unpacked"] = _range_text(p["unpacked_dimensions"])
        else:
            if "range" in p:
                port["range"] = p["range"]
            elif "msb" in p or "lsb" in p:  # Read earlier compact files too.
                port["range"] = _range_text([p], "msb", "lsb")
            elif "packed" in p:
                port["range"] = _range_text(p["packed"], "msb", "lsb")
            elif "width" in p:
                port["width"] = p["width"]
            if "unpacked" in p:
                port["unpacked"] = (p["unpacked"] if isinstance(p["unpacked"], str)
                                    else _range_text(p["unpacked"], "msb", "lsb"))
        port["name"] = p["name"]
        if "description" in p:
            if not isinstance(p["description"], str):
                raise RTLExtractionError(f"description must be text for {p['name']}")
            if p["description"]:
                port["description"] = p["description"]
        definition["ports"].append(port)
    if groups is not None:
        definition["groups"] = groups
    elif contract.get("groups"):
        definition["groups"] = contract["groups"]
    return definition


def format_interface_json(definition: dict) -> str:
    """Keep parameter/port records on one line with aligned columns."""
    lines = ["{"]
    items = list(definition.items())
    for index, (key, value) in enumerate(items):
        comma = "," if index < len(items) - 1 else ""
        if key in ("parameters", "ports") and value:
            rows = []
            for record in value:
                order = ("direction", "width", "range", "unpacked", "name", "description") if key == "ports" else ("name", "width")
                rows.append([f'{json.dumps(k)}: {json.dumps(record[k])}' for k in order if k in record])
            # The final cell stays unpadded; padding before it aligns the names.
            count = max(len(row) for row in rows)
            widths = [max((len(row[i]) for row in rows if i < len(row) - 1), default=0)
                      for i in range(count - 1)]
            lines.append(f'  "{key}": [')
            for i, row in enumerate(rows):
                cells = [cell.ljust(widths[j] + 3) if j < len(row) - 1 else cell
                         for j, cell in enumerate(row)]
                lines.append("    {" + ", ".join(cells) + "}" + ("," if i < len(rows) - 1 else ""))
            lines.append("  ]" + comma)
        else:
            text = json.dumps(value, indent=2) if isinstance(value, dict) else json.dumps(value)
            lines.append(f"  {json.dumps(key)}: " + text.replace("\n", "\n  ") + comma)
    return "\n".join(lines + ["}", ""])


def _name(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(IDENT, value) is None:
        raise RTLExtractionError(f"unsupported generated identifier: {value!r}")
    # A suffix keeps default interface names clear of HDL keywords; explicit names must be safe too.
    if value in RESERVED | {"dut", "tb", "monitor"}:
        raise RTLExtractionError(f"reserved generated identifier: {value}")
    return value


def _dimensions(dimensions: list[dict]) -> str:
    out = []
    for d in dimensions:
        if any(type(d.get(k)) is not int or abs(d[k]) >= 2 ** 31 for k in ("left", "right")):
            raise RTLExtractionError("invalid resolved dimension in extraction artifact")
        out.append(f"[{d['left']}:{d['right']}]")
    return "".join(out)


def build_interface(contract: dict, *, interface_name: str | None = None,
                    groups: dict | None = None, clock: str | None = None, edge: str = "posedge",
                    emit_sv: bool = False) -> dict[str, str]:
    """Build the canonical JSON definition; optionally export a single SV port bundle.

    Definitions are concrete for the extracted configuration. They deliberately do not guess a
    protocol, active reset level, clock, skew, assertions, or stimulus from signal names.
    """
    if "top_source" not in contract:
        if emit_sv or interface_name or clock or edge != "posedge":
            raise RTLExtractionError("SV export needs original RTL; use rtl-interfaces --build --emit-sv")
        definition = interface_definition(contract, groups=groups)
        _validate_definition(definition)
        return {"interface_definition.json": format_interface_json(definition)}
    top = _name(contract["top"])
    name = _name(interface_name or f"{top}_if")
    ports = contract["ports"]
    if not ports:
        raise RTLExtractionError("cannot build an interface for a module without ports")
    names = [_name(p["name"]) for p in ports]
    if len(set(names)) != len(names):
        raise RTLExtractionError("duplicate ports in extraction artifact")
    if any(n in {"driver_cb", "monitor_cb"} for n in names):
        raise RTLExtractionError("port name collides with a generated clocking block")
    if edge not in ("posedge", "negedge"):
        raise RTLExtractionError("clock edge must be posedge or negedge")
    if clock:
        cp = next((p for p in ports if p["name"] == clock), None)
        if (cp is None or cp["direction"] != "input" or cp["width_bits"] != 1
                or cp["unpacked_dimensions"]):
            raise RTLExtractionError("clock must name a scalar DUT input")
        if any(p["direction"] == "inout" for p in ports):
            raise RTLExtractionError("clocking blocks with bidirectional ports require a reviewed drive policy")
    groups = groups if groups is not None else {"ports": names}
    if not isinstance(groups, dict) or not groups:
        raise RTLExtractionError("groups must be an object mapping group names to nonempty signal lists")
    flat = []
    for group, signals in groups.items():
        if not isinstance(group, str) or not group.strip() or any(c in group for c in "\r\n"):
            raise RTLExtractionError("group names must be nonempty single-line strings")
        if not isinstance(signals, list) or not signals or any(not isinstance(s, str) for s in signals):
            raise RTLExtractionError(f"group {group} must contain a nonempty list of signal names")
        flat.extend(signals)
    if len(flat) != len(set(flat)) or set(flat) != set(names):
        raise RTLExtractionError("groups must cover every port exactly once with no unknown signals")
    by_name = {p["name"]: p for p in ports}
    for p in ports:
        packed, unpacked = p["packed_dimensions"], p["unpacked_dimensions"]
        _dimensions(packed)
        _dimensions(unpacked)
        width = math.prod(abs(d["left"] - d["right"]) + 1 for d in packed)
        total = width * math.prod(abs(d["left"] - d["right"]) + 1 for d in unpacked)
        if (type(p["signed"]) is not bool or type(p["width_bits"]) is not int
                or type(p["total_bits"]) is not int or p["width_bits"] != width
                or p["total_bits"] != total or total > 1_048_576):
            raise RTLExtractionError(f"inconsistent resolved port shape: {p['name']}")
    definition = interface_definition(contract, groups=groups if groups != {"ports": names} else None)
    _validate_definition(definition)
    artifacts = {"interface_definition.json": format_interface_json(definition)}
    if not emit_sv:
        return artifacts
    lines = ["// Generated by dv-agent; configuration-specific declarations, NEEDS_REVIEW.",
             "// No protocol behavior or reset polarity inferred.",
             f"interface {name};"]
    for group, signals in groups.items():
        lines += [f"  // Group: {group} (user supplied)" if groups != {"ports": names} else "  // All DUT ports"]
        for signal in signals:
            p = by_name[signal]
            if p["direction"] not in ("input", "output", "inout") or p["data_type"] not in ("logic", "bit"):
                raise RTLExtractionError(f"unsupported direction or type for {signal}")
            packed = _dimensions(p["packed_dimensions"])
            unpacked = _dimensions(p["unpacked_dimensions"])
            dtype = "tri" if p["direction"] == "inout" else p["data_type"]
            signed = " signed" if p["signed"] else ""
            lines.append(f"  {dtype}{signed}{' ' + packed if packed else ''} {signal}{unpacked};")
    inverse = {"input": "output", "output": "input", "inout": "inout"}
    for view in ("dut", "tb", "monitor"):
        entries = []
        for p in ports:
            direction = p["direction"] if view == "dut" else inverse[p["direction"]] if view == "tb" else "input"
            entries.append(f"{direction} {p['name']}")
        lines += ["", f"  modport {view} (", "    " + ",\n    ".join(entries), "  );"]
    if clock:
        for cb in ("driver_cb", "monitor_cb"):
            lines += ["", f"  clocking {cb} @({edge} {clock});", "    default input #1step output #0;"]
            for p in ports:
                if p["name"] == clock:
                    continue
                direction = "input" if cb == "monitor_cb" else inverse[p["direction"]]
                lines.append(f"    {direction} {p['name']};")
            lines.append("  endclocking")
    lines += [f"endinterface : {name}", ""]
    # This is an undriven connection scaffold, not a simulation or a generated testbench.
    connection = ["// Connection scaffold; add reviewed stimulus and clock/reset generation separately.",
                  f"module {name}_connections;", f"  {name} bus();"]
    params = [p for p in contract["parameters"] if not p["local"]]
    if params:
        bindings = []
        for p in params:
            parameter = _name(p["name"])
            if type(p["value"]) is not int or not -(2 ** 31) <= p["value"] < 2 ** 31:
                raise RTLExtractionError("invalid resolved parameter in extraction artifact")
            bindings.append(f".{parameter}({p['value']})")
        connection += [f"  {top} #(", "    " + ",\n    ".join(bindings), "  ) dut ("]
    else:
        connection.append(f"  {top} dut (")
    connection += ["    " + ",\n    ".join(f".{p['name']}(bus.{p['name']})" for p in ports),
                   "  );", f"endmodule : {name}_connections", ""]
    if emit_sv:
        artifacts.update({f"{name}.sv": "\n".join(lines),
                          f"{name}_connections.sv": "\n".join(connection)})
    return artifacts


def _validate_definition(definition: dict) -> None:
    """Check only essentials needed to use a wiring definition."""
    names = []
    for p in definition["ports"]:
        names.append(_name(p["name"]))
        if p["direction"] not in ("input", "output", "inout"):
            raise RTLExtractionError(f"invalid DUT-relative direction for {p['name']}")
        if ("width" in p) == ("range" in p):
            raise RTLExtractionError(f"provide width or range for {p['name']}")
        if "width" in p and (type(p["width"]) is not int or p["width"] <= 0):
            raise RTLExtractionError(f"invalid width for {p['name']}")
        width = _range_width(p["range"]) if "range" in p else p["width"]
        if width * (_range_width(p["unpacked"]) if "unpacked" in p else 1) > 1_048_576:
            raise RTLExtractionError(f"port {p['name']} exceeds the 1048576-bit port budget")
    if not names or len(names) != len(set(names)):
        raise RTLExtractionError("interface must contain unique ports")
    groups = definition.get("groups")
    if groups is not None:
        if not isinstance(groups, dict) or not groups:
            raise RTLExtractionError("groups must map names to nonempty signal lists")
        flat = []
        for group, signals in groups.items():
            if not isinstance(group, str) or not group.strip() or not isinstance(signals, list) or not signals:
                raise RTLExtractionError("groups must map names to nonempty signal lists")
            flat.extend(signals)
        if len(flat) != len(set(flat)) or set(flat) != set(names):
            raise RTLExtractionError("groups must cover every port exactly once with no unknown signals")


def write_artifacts(out: Path, artifacts: dict[str, str], *, protected: list[Path]) -> None:
    """Refuse any source/manifest overwrite before writing the first generated file."""
    protected_paths = {p.resolve() for p in protected}
    for name in artifacts:
        target = out / name
        if target.resolve() in protected_paths or target.is_symlink():
            raise RTLExtractionError(f"refusing to overwrite source or linked artifact: {target}")
    for name, text in artifacts.items():
        atomic_write_text(out / name, text)
