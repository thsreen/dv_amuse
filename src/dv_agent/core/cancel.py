"""Cooperative cancellation for a tool that timed out.

The orchestrator can stop waiting for a tool, but a Python thread cannot be killed. Without a signal the
abandoned worker keeps making paid model calls and can race the owner's retry on the same files. A
timed-out tool's token is set; the model client checks it before every attempt and stops. A request already
on the wire finishes (bounded by the client timeout); no new one starts.

The token travels in a context variable, so worker pools started by the tool must wrap their callables
with `bind`.
"""
import contextvars
import threading
from typing import Callable

_TOKEN: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar("dv_cancel_token", default=None)


def _with_token(token: threading.Event | None, fn: Callable, *args, **kwargs):
    reset = _TOKEN.set(token)
    try:
        return fn(*args, **kwargs)
    finally:
        _TOKEN.reset(reset)


def in_scope(token: threading.Event, fn: Callable) -> Callable[[], object]:
    """Return a zero-argument callable that runs fn with this cancellation token active."""
    return lambda: _with_token(token, fn)


def bind(fn: Callable) -> Callable:
    """Carry the current token into a worker-pool thread (safe to call from several threads at once)."""
    token = _TOKEN.get()
    return lambda *args, **kwargs: _with_token(token, fn, *args, **kwargs)


def is_cancelled() -> bool:
    token = _TOKEN.get()
    return token is not None and token.is_set()
