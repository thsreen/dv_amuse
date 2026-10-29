"""Terminal progress reporting for long stages (stderr only, opt-in).

Library code calls :func:`emit` at stage starts, per-iteration steps, and
completions. The sink is process-global and defaults to silent so library use
and tests stay quiet; the CLI routes it to stderr, keeping stdout as pure JSON.
"""
import sys
from typing import Callable

Sink = Callable[[str], None]

_sink: Sink | None = None


def set_sink(sink: Sink | None) -> None:
    """Install (or clear, with None) the process-global progress sink."""
    global _sink
    _sink = sink


def stderr_sink(message: str) -> None:
    print(f"dv-agent: {message}", file=sys.stderr, flush=True)


def emit(message: str) -> None:
    """Report one progress line; a no-op unless a sink is installed."""
    if _sink is not None:
        _sink(message)
