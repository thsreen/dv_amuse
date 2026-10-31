"""Reusable UVM verification components (UVCs): fixed SystemVerilog source, not templates.

Nothing here has placeholders or is rendered. Generation copies these files unchanged into a project's
`common_uvc/<name>/` folder; a project customizes them only through their configuration objects
(`clock_cfg`, `reset_cfg`, `common_cfg`) and UVM factory overrides. Templates that are filled in per design
live in `dv_agent/templates/`.
"""
from pathlib import Path

UVC_ROOT = Path(__file__).resolve().parent
COMMON_UVCS = ("clock", "reset", "common")  # compile order: clock and reset packages before common


def sources(name):
    """SystemVerilog files of one UVC, in a stable order."""
    return [p for p in sorted((UVC_ROOT / name).iterdir()) if p.suffix in (".sv", ".svh")]
