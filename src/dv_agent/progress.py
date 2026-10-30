"""Terminal progress reporting for long stages (stderr only, opt-in).

Library code calls :func:`emit` at stage starts, per-iteration steps, and
completions. The sink is thread-local and defaults to silent so library use
and tests stay quiet; the CLI routes it to stderr, keeping stdout as pure JSON.
An optional process-wide sink lets worker threads report too (each line is
written atomically). None means unset at both levels: a thread with no
thread-local sink falls through to the global one.
"""
import sys
import threading
from typing import Callable

Sink = Callable[[str], None]

_state = threading.local()
_global_sink: Sink | None = None
_global_lock = threading.Lock()


def set_sink(sink: Sink | None) -> None:
    """Install (or clear) the progress sink for this execution thread."""
    _state.sink = sink


def set_global_sink(sink: Sink | None) -> None:
    """Install (or clear) the process-wide sink used when a thread has none."""
    global _global_sink
    _global_sink = sink


def thread_tag() -> str:
    """Worker identity suffix; empty on the main thread to keep output stable."""
    current = threading.current_thread()
    return "" if current is threading.main_thread() else f" [{current.name}]"


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
    """Report one progress line; silent unless a thread-local or global sink is installed."""
    sink = getattr(_state, "sink", None)
    if sink is None:
        sink = _global_sink
        if sink is None:
            return
        with _global_lock:
            sink(message)
        return
    sink(message)
