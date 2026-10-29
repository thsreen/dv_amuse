"""Offline CLI adapter for the separate coding flow."""
import json
from argparse import Namespace
from pathlib import Path

from .builder import build_interface, format_interface_json, interface_definition, write_artifacts
from .extractor import extract_interface
from .source import RTLExtractionError


def _assignments(items: list[str], *, define: bool) -> dict[str, str]:
    result = {}
    for item in items:
        name, sep, value = item.partition("=")
        if not name or (not sep and not define) or (sep and not value.strip()):
            raise RTLExtractionError(f"expected NAME{'[=VALUE]' if define else '=VALUE'}: {item!r}")
        if name in result:
            raise RTLExtractionError(f"duplicate command-line assignment: {name}")
        result[name] = value if sep else "1"
    return result


def _read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RTLExtractionError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(obj, dict):
        raise RTLExtractionError(f"expected JSON object: {path}")
    return obj


def run_rtl_command(args: Namespace) -> dict:
    try:
        artifacts = {}
        protected = [args.groups] if args.groups else []
        if args.cmd == "rtl-interfaces":
            if not args.build and (args.name or args.groups or args.clock or args.emit_sv or args.edge != "posedge"):
                raise RTLExtractionError("--name, --groups, --clock, --edge and --emit-sv require --build")
            contract = extract_interface(args.files, args.top, include_dirs=args.include_dir,
                                         defines=_assignments(args.define, define=True),
                                         overrides=_assignments(args.parameter, define=False))
            artifacts["rtl_interfaces.json"] = format_interface_json(interface_definition(contract))
            build = args.build
        else:
            contract = _read_json(args.contract)
            protected.append(args.contract)
            build = True
        protected += [Path(s["path"] if isinstance(s, dict) else s) for s in contract["sources"]]
        if build:
            artifacts.update(build_interface(contract, interface_name=args.name,
                                             groups=_read_json(args.groups) if args.groups else None,
                                             clock=args.clock, edge=args.edge, emit_sv=args.emit_sv))
        write_artifacts(args.out, artifacts, protected=protected)
        return dict(ports=len(contract["ports"]), out=str(args.out), artifacts=list(artifacts))
    except (OSError, KeyError, TypeError) as exc:
        raise RTLExtractionError(f"invalid RTL input/artifact or output path: {exc}") from exc
