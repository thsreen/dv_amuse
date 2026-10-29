"""Standalone offline CLI for RTL extraction and interface building."""
import argparse
import json
import sys
from pathlib import Path

from .commands import run_rtl_command


def add_commands(sub: argparse._SubParsersAction) -> None:
    """Share command definitions with the existing dv-agent entry point."""
    pr = sub.add_parser("rtl-interfaces", help="extract configured module ports from explicit RTL files (offline)")
    pr.add_argument("files", type=Path, nargs="+")
    pr.add_argument("--top", required=True, help="exact module name; no automatic top selection")
    pr.add_argument("-I", "--include-dir", type=Path, action="append", default=[])
    pr.add_argument("-D", "--define", action="append", default=[], help="NAME or NAME=VALUE")
    pr.add_argument("-P", "--parameter", action="append", default=[], help="NAME=integer expression")
    pr.add_argument("--out", type=Path, required=True)
    pr.add_argument("--build", action="store_true", help="also build interface_definition.json")
    pr.add_argument("--emit-sv", action="store_true", help="optional SV export (requires --build)")
    pr.add_argument("--name", help="generated interface name (with --build)")
    pr.add_argument("--groups", type=Path, help="JSON mapping group names to signal lists (with --build)")
    pr.add_argument("--clock", help="explicit scalar input clock for optional clocking blocks (with --build)")
    pr.add_argument("--edge", choices=("posedge", "negedge"), default="posedge")

    pb = sub.add_parser("build-interface", help="build interface JSON from saved RTL extraction")
    pb.add_argument("contract", type=Path, help="rtl_interfaces.json")
    pb.add_argument("--out", type=Path, required=True)
    pb.add_argument("--name")
    pb.add_argument("--groups", type=Path)
    pb.add_argument("--clock")
    pb.add_argument("--emit-sv", action="store_true")
    pb.add_argument("--edge", choices=("posedge", "negedge"), default="posedge")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rtl-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add_commands(sub)
    from .graph_commands import add_graph_commands, run_graph_command
    add_graph_commands(sub)
    args = parser.parse_args(argv)
    try:
        result = (run_rtl_command(args) if args.cmd in ("rtl-interfaces", "build-interface")
                  else run_graph_command(args))
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
