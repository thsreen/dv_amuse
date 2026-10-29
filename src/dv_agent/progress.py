"""Terminal progress reporting for long stages (stderr only, opt-in).

Library code calls :func:`emit` at stage starts, per-iteration steps, and
completions. The sink is thread-local and defaults to silent so library use
and tests stay quiet; the CLI routes it to stderr, keeping stdout as pure JSON.
"""
import sys
import threading
from typing import Callable

Sink = Callable[[str], None]

_state = threading.local()


def set_sink(sink: Sink | None) -> None:
    """Install (or clear) the progress sink for this execution thread."""
    _state.sink = sink


def set_event_sink(sink: Callable[[dict], None] | None) -> None:
    """Install structured stage events for an orchestrated run."""
    _state.event_sink = sink


def emit_event(kind: str, **fields) -> None:
    sink = getattr(_state, "event_sink", None)
    if sink is not None:
        sink(dict(kind=kind, **fields))


def stderr_sink(message: str) -> None:
    print(f"dv-agent: {message}", file=sys.stderr, flush=True)


def emit(message: str) -> None:
    """Report one progress line; a no-op unless a sink is installed."""
    sink = getattr(_state, "sink", None)
    if sink is not None:
        sink(message)
