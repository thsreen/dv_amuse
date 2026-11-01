"""Keep a test plan to the one build configuration the request selected.

A specification often documents several build modes. When the request selects one, the interface JSON was extracted with
its compile defines, and the plan must describe that build only. The selection comes from the request; the specification
stays the authority for behaviour, so documented values are never rewritten: a signal keeps its documented width and gains
`configured_width`, and anything outside the configuration is listed in the plan with its reason, not silently lost.
Design-agnostic: the other modes are found from the specification's own width alternatives. With no define selected, nothing
changes.
"""
import json
import re
from pathlib import Path

from ..codegen.port_comparison import width, width_options


def norm(name) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def load_configuration(path) -> dict | None:
    """The selected configuration from an interface JSON, or None when the request selected none."""
    if path is None or not Path(path).is_file():
        return None
    definition = json.loads(Path(path).read_text())
    defines = definition.get("defines") or []
    if not defines:
        return None
    numbers = [int(n) for d in defines for n in re.findall(r"(?:^|_)(\d+)(?:_|=|$)", d)]
    return dict(defines=list(defines), selected_bits=numbers[0] if numbers else None, excluded_bits=[], ports=definition.get("ports", []))


def _signals(interfaces):
    yield from interfaces.get("signals", [])
    for group in interfaces.get("groups", []):
        yield from group.get("signals", [])


def apply_interfaces(interfaces, config) -> None:
    """Configured width per signal, inactive conditional ports, and the widths of the other modes."""
    if not config or not interfaces:
        return
    ports = {norm(p["name"]): p for p in config["ports"]}
    excluded = set(config["excluded_bits"])
    for signal in _signals(interfaces):
        choices = width_options(signal.get("width"))
        port = ports.get(norm(signal.get("name", "")))
        if choices:
            if config["selected_bits"] in choices:
                excluded |= choices - {config["selected_bits"]}
            if port is None:
                fits = [p for p in config["ports"] if p["direction"] == signal.get("direction") and width(p.get("width", p.get("range"))) in choices
                        and not any(norm(s.get("name", "")) == norm(p["name"]) for s in _signals(interfaces))]
                port = fits[0] if len(fits) == 1 else None
            bits = width(port.get("width", port.get("range"))) if port else None
            if bits in choices:
                signal["configured_width"] = bits
        elif signal.get("availability") and port is None:
            signal["inactive_in_configuration"] = f"Not in this build: {signal['availability']}"
    config["excluded_bits"] = sorted(excluded)


def _mentions_excluded(text, config) -> str | None:
    for bits in config["excluded_bits"]:
        if re.search(rf"\b{bits}[\s-]*bits?\b", text or "", re.I):
            return f"{bits}-bit mode"
    return None


def apply_registers(registers, config) -> None:
    """Registers and fields available only in another mode leave the map before any section uses it."""
    if not config or not registers:
        return
    kept, removed = [], []
    for register in registers.get("registers", []):
        reason = _mentions_excluded(register.get("availability", ""), config)
        (removed if reason else kept).append(dict(name=register.get("name", ""), reason=f"Available only in {reason}") if reason else register)
    registers["registers"] = kept
    names = {r["name"] for r in removed}
    registers["configurable"] = [f for f in registers.get("configurable", [])
                                 if f.get("register_name") not in names and not _mentions_excluded(f.get("availability", ""), config)]
    registers["conflicts"] = [c for c in registers.get("conflicts", []) if not any(n in json.dumps(c) for n in names)]
    config["inactive_registers"] = config.get("inactive_registers", []) + removed


def prompt_view(config) -> dict:
    return dict(defines=config["defines"], selected_data_bits=config["selected_bits"], other_modes_bits=config["excluded_bits"])


def _entry_text(entry) -> str:
    return " ".join([str(entry.get("text", "")), *[str(d) for d in entry.get("details", [])]])


def apply_sections(doc, config) -> None:
    """The final guard: an entry about another mode leaves the plan and is listed, with the assertion pairing kept intact."""
    if not config:
        return
    from .testplan_doc import unpaired_assertions
    by_id = {s["id"]: s for s in doc["sections"]}
    checks, coverage = by_id.get("checks", {}).get("entries"), by_id.get("coverage", {}).get("entries")
    paired = checks is not None and coverage is not None
    already_unpaired = set(unpaired_assertions(checks, coverage)[0]) if paired else set()
    excluded = list((doc.get("configuration") or {}).get("excluded_items", []))  # a re-saved snapshot keeps earlier ones
    def remove(section, entry, reason):
        at = next(i for i, e in enumerate(section["entries"]) if e is entry)
        del section["entries"][at]
        for subsection in section.get("subsections") or []:  # subsections index into the section's entries
            if "entry_indexes" in subsection:
                subsection["entry_indexes"] = [i - (i > at) for i in subsection["entry_indexes"] if i != at]
        excluded.append(dict(section=section.get("heading", section["id"]), text=str(entry.get("text", "")), reason=reason))
    for section in doc["sections"]:
        for entry in list(section.get("entries") or []):
            reason = _mentions_excluded(_entry_text(entry), config)
            if reason:
                remove(section, entry, f"About {reason}")
    if paired:
        orphans = set(unpaired_assertions(checks, coverage)[0]) - already_unpaired
        for entry in list(checks):
            if entry.get("kind") == "assertion" and any(label in _entry_text(entry) for label in orphans):
                remove(by_id["checks"], entry, "Its cover property is outside this configuration")
    # Generated prose cannot be cut safely: the prompt forbids it, and any mention left is flagged for the reviewer.
    notes = [f"{s.get('heading', s['id'])} still mentions {reason}; review it against this configuration."
             for s in doc["sections"] for key in ("strategy", "configurations")
             if (reason := _mentions_excluded(json.dumps(s.get(key) or ""), config))]
    doc["configuration"] = dict(review_notes=notes, defines=config["defines"], selected_data_bits=config["selected_bits"], other_modes_bits=config["excluded_bits"],
                                inactive_registers=config.get("inactive_registers", []),
                                inactive_ports=sorted({s["name"]: s["inactive_in_configuration"] for s in _signals(doc.get("interfaces") or {})
                                                       if s.get("inactive_in_configuration")}.items()),
                                excluded_items=excluded)


def render(doc) -> list[str]:
    config = doc.get("configuration")
    if not config:
        return []
    lines = [f"> **Build configuration (from the request): {', '.join(config['defines'])}.** This plan covers this build only.", ""]
    lines += [f"> **NEEDS_REVIEW:** {note}" for note in config.get("review_notes", [])] + ([""] if config.get("review_notes") else [])
    rows = ([f"- Port {name}: {reason}" for name, reason in config["inactive_ports"]]
            + [f"- Register {r['name']}: {r['reason']}" for r in config["inactive_registers"]]
            + [f"- {i['section']}: {i['text']} ({i['reason']})" for i in config["excluded_items"]])
    if rows:
        lines += ["<details>", f"<summary>Outside this configuration ({len(rows)} items, not planned)</summary>", "", *rows, "", "</details>", ""]
    return lines
