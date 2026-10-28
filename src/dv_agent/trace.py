"""Run tracing: Langfuse when configured, always mirrored to a local JSONL sink.

The local sink is the durable lineage record; Langfuse is the browsable mirror. A Langfuse
failure disables Langfuse for the rest of the run instead of breaking the pipeline.
"""
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def langfuse_configured() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
                and os.getenv("LANGFUSE_SECRET_KEY", "").strip())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Span:
    def __init__(self, tracer: "Tracer", record: dict, lf_obs: Any = None):
        self._tracer = tracer
        self.record = record
        self._lf = lf_obs

    @property
    def id(self) -> str:
        return self.record["span_id"]

    @property
    def trace_id(self) -> str:
        return self.record["trace_id"]

    def update(self, *, output: Any = None, metadata: dict | None = None, level: str | None = None,
               status_message: str | None = None, usage: dict | None = None) -> None:
        if output is not None:
            self.record["output"] = output
        if metadata:
            self.record["metadata"] = {**self.record.get("metadata", {}), **metadata}
        if level:
            self.record["level"] = level
        if status_message:
            self.record["status_message"] = status_message
        if usage:
            self.record["usage"] = usage
        if self._lf is not None:
            kwargs: dict[str, Any] = {k: v for k, v in dict(
                output=output, metadata=metadata, level=level, status_message=status_message).items()
                if v is not None}
            if usage:
                kwargs["usage_details"] = usage
            self._tracer._lf_call(self._lf.update, **kwargs)


class Tracer:
    """One trace per pipeline run. Use as a context manager; it opens the root span."""

    def __init__(self, sink: Path, name: str, *, input: Any = None, metadata: dict | None = None,
                 client: Any = None, use_langfuse: bool | None = None):
        from langfuse import Langfuse

        self.sink = sink
        self.name = name
        self.trace_id = Langfuse.create_trace_id()
        self._root_input = input
        self._root_metadata = metadata or {}
        self._stack: list[str] = []
        self.langfuse_error: str | None = None
        if use_langfuse is None:
            use_langfuse = client is not None or langfuse_configured()
        self._lf_client = None
        if use_langfuse:
            try:
                self._lf_client = client or Langfuse()
            except Exception as exc:
                self.langfuse_error = f"init failed: {type(exc).__name__}"
        self._root_cm = None
        self.root: Span | None = None

    @property
    def langfuse_active(self) -> bool:
        return self._lf_client is not None

    def _lf_call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            self.langfuse_error = f"{getattr(fn, '__name__', 'call')} failed: {type(exc).__name__}"
            self._lf_client = None
            return None

    def trace_url(self) -> str | None:
        if self._lf_client is None:
            return None
        return self._lf_call(self._lf_client.get_trace_url, trace_id=self.trace_id)

    def __enter__(self) -> "Tracer":
        self._root_cm = self.span(self.name, as_type="chain", input=self._root_input,
                                  metadata=self._root_metadata, _root=True)
        self.root = self._root_cm.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._root_cm.__exit__(exc_type, exc, tb)
        if self._lf_client is not None:
            self._lf_call(self._lf_client.flush)

    @contextmanager
    def span(self, name: str, *, as_type: str = "span", input: Any = None,
             metadata: dict | None = None, model: str | None = None,
             _root: bool = False) -> Iterator[Span]:
        lf_cm, lf_obs = None, None
        if self._lf_client is not None:
            kwargs: dict[str, Any] = dict(name=name, as_type=as_type, input=input, metadata=metadata)
            if model:
                kwargs["model"] = model
            if _root:
                kwargs["trace_context"] = {"trace_id": self.trace_id}
            lf_cm = self._lf_call(self._lf_client.start_as_current_observation, **kwargs)
            if lf_cm is not None:
                lf_obs = self._lf_call(lf_cm.__enter__)
                if lf_obs is None:
                    lf_cm = None
        span_id = getattr(lf_obs, "id", None) or uuid.uuid4().hex[:16]
        record = dict(trace_id=self.trace_id, span_id=span_id,
                      parent_id=self._stack[-1] if self._stack else None, name=name, type=as_type,
                      start_utc=_now(), input=input, metadata=metadata or {})
        if model:
            record["model"] = model
        self._stack.append(span_id)
        started = time.perf_counter()
        span = Span(self, record, lf_obs)
        try:
            yield span
        except Exception as exc:
            span.update(level="ERROR", status_message=type(exc).__name__)
            raise
        finally:
            self._stack.pop()
            record["end_utc"] = _now()
            record["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
            if lf_cm is not None:
                self._lf_call(lf_cm.__exit__, None, None, None)
            self.sink.parent.mkdir(parents=True, exist_ok=True)
            with self.sink.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")


def read_trace(sink: Path, trace_id: str | None = None) -> list[dict]:
    if not sink.exists():
        return []
    with sink.open(encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    return [r for r in records if trace_id is None or r["trace_id"] == trace_id]
