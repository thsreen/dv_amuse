"""Meta Model API client with strict JSON-schema output, bounded retries, and a response cache.

The API contract (Responses API at META_BASE_URL) follows old_reference/silicon-copilot and is
not yet verified live in this workspace. META_API_STYLE=chat switches to chat.completions.
"""
import hashlib
import math
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from . import cancel
from .fsutil import atomic_write_text
from .progress import emit, thread_tag
from .trace import Tracer
from .usage import estimate_usage

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3-contributor"
API_STYLES = ("responses", "chat")
_REQUEST_CONTEXT = ContextVar('llm_request_context', default=None)
_REQUEST_LOG_LOCK = threading.Lock()


@contextmanager
def _request_logging(tracer, span_id):
    token = _REQUEST_CONTEXT.set((tracer, span_id))
    try:
        yield
    finally:
        _REQUEST_CONTEXT.reset(token)


def _request_event(event, **fields):
    """Persist attempt metadata immediately; never include headers, URLs or provider bodies."""
    context = _REQUEST_CONTEXT.get()
    if context is None:
        return
    tracer, span_id = context
    record = dict(ts=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                  event=event, trace_id=tracer.trace_id, span_id=span_id,
                  thread=threading.current_thread().name, **fields)
    path = tracer.sink.parent / 'llm_requests.jsonl'
    with _REQUEST_LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, default=str) + '\n')


def _error_types(error):
    types = []
    while error is not None and len(types) < 4:
        types.append(type(error).__name__)
        error = error.__cause__
    return types


class LLMError(RuntimeError):
    def __init__(self, kind: str, message: str, *, usage: dict | None = None,
                 response_id: str | None = None, token_exhausted: bool = False):
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.usage = usage or {}
        self.response_id = response_id
        self.token_exhausted = token_exhausted
        self.attempts: list[dict] = []


@dataclass
class LLMResult:
    data: dict
    model: str
    response_id: str | None = None
    cached: bool = False
    usage: dict = field(default_factory=dict)
    attempts: list[dict] = field(default_factory=list)


class LLM(Protocol):
    model: str

    def structured(self, *, name: str, instructions: str, payload: dict, schema: dict,
                   tracer: Tracer | None = None, _span_parent: str | None = None) -> LLMResult: ...


def _detail(usage: Any, group: str, key: str) -> int:
    return int(getattr(getattr(usage, group, None), key, 0) or 0)


def usage_from_responses(usage: Any) -> dict:
    if not usage:
        return {}
    return dict(input=int(usage.input_tokens or 0), output=int(usage.output_tokens or 0),
                reasoning=_detail(usage, "output_tokens_details", "reasoning_tokens"),
                cached_input=_detail(usage, "input_tokens_details", "cached_tokens"))


def usage_from_chat(usage: Any) -> dict:
    if not usage:
        return {}
    return dict(input=int(usage.prompt_tokens or 0), output=int(usage.completion_tokens or 0),
                reasoning=_detail(usage, "completion_tokens_details", "reasoning_tokens"),
                cached_input=_detail(usage, "prompt_tokens_details", "cached_tokens"))


def _cache_key(model: str, name: str, instructions: str, payload: dict, schema: dict) -> str:
    blob = json.dumps([model, name, instructions, payload, schema], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _done_line(name: str, start: float, result: LLMResult) -> str:
    parts = [f"{time.perf_counter() - start:.1f}s", f"attempts {len(result.attempts)}"]
    usage = result.usage or {}
    if usage.get("input") or usage.get("output"):
        parts.append(f"in {usage.get('input', 0)}/out {usage.get('output', 0)}")
    if result.cached:
        parts.append("cached")
    return f"llm call {name!r} done ({', '.join(parts)}){thread_tag()}"


def _fail_line(name: str, start: float, exc: LLMError) -> str:
    return f"llm call {name!r} failed: {exc.kind} after {time.perf_counter() - start:.1f}s{thread_tag()}"


class _Base:
    model: str
    cache_dir: Path | None

    def _call(self, name: str, instructions: str, payload: dict, schema: dict) -> LLMResult:
        raise NotImplementedError

    def structured(self, *, name: str, instructions: str, payload: dict, schema: dict,
                   tracer: Tracer | None = None, _span_parent: str | None = None) -> LLMResult:
        key = _cache_key(self.model, name, instructions, payload, schema)
        cache_file = self.cache_dir / f"{key}.json" if self.cache_dir else None
        start = time.perf_counter()
        report = tracer is not None or _REQUEST_CONTEXT.get() is None
        if report: emit(f"llm call {name!r} start (model {self.model}){thread_tag()}")
        if tracer is None:
            try:
                result = self._cached_call(cache_file, name, instructions, payload, schema)
            except LLMError as exc:
                if report: emit(_fail_line(name, start, exc))
                raise
            if report: emit(_done_line(name, start, result))
            return result
        with tracer.span(f"llm:{name}", as_type="generation", model=self.model,
                         input={"instructions": instructions, "payload": payload},
                         metadata={"cache_key": key}, _parent=_span_parent) as span, _request_logging(tracer, span.id):
            try:
                result = self._cached_call(cache_file, name, instructions, payload, schema)
            except LLMError as exc:
                span.update(usage=exc.usage, metadata={"api_attempts": exc.attempts,
                            "response_id": exc.response_id, "error_kind": exc.kind,
                            "error_detail": str(exc)}, status_message=str(exc))
                emit(_fail_line(name, start, exc))
                raise
            usage = result.usage or estimate_usage(instructions, payload, schema, result.data)
            span.update(output=result.data, usage=usage,
                        metadata={"cached": result.cached, "response_id": result.response_id,
                                  "usage_estimated": not result.usage})
            span.update(metadata={"api_attempts": [] if result.cached else result.attempts})
            if result.cached:
                _request_event('cache_hit', name=name, model=self.model, cache_key=key)
            emit(_done_line(name, start, result))
            return result

    def _cached_call(self, cache_file: Path | None, name: str, instructions: str, payload: dict,
                     schema: dict) -> LLMResult:
        if cache_file and cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                return LLMResult(data=cached["data"], model=cached["model"],
                                 response_id=cached.get("response_id"), cached=True,
                                 usage=cached.get("usage", {}))
            except (json.JSONDecodeError, KeyError, TypeError):
                cache_file.unlink(missing_ok=True)  # corrupt entry: refetch
        result = self._call(name, instructions, payload, schema)
        if cache_file:
            atomic_write_text(cache_file, json.dumps(dict(data=result.data, model=result.model,
                                                          response_id=result.response_id,
                                                          usage=result.usage), indent=1))
        return result


class MetaClient(_Base):
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, api_style: str | None = None, timeout: float | None = None,
                 max_attempts: int = 5, max_output_tokens: int | None = None,
                 max_output_tokens_ceiling: int | None = None,
                 cache_dir: Path | None = None, client: Any = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.api_key = api_key if api_key is not None else os.getenv("MODEL_API_KEY", "").strip()
        self.base_url = base_url or os.getenv("META_BASE_URL", DEFAULT_BASE_URL)
        self.model = model or os.getenv("META_MODEL", DEFAULT_MODEL)
        self.api_style = (api_style or os.getenv("META_API_STYLE", "") or "responses").strip().lower()
        if self.api_style not in API_STYLES:
            raise ValueError(f"META_API_STYLE must be one of {API_STYLES}, got {self.api_style!r}")
        raw_tokens = max_output_tokens if max_output_tokens is not None else os.getenv("META_MAX_OUTPUT_TOKENS", "8192")
        try:
            self.max_output_tokens = int(raw_tokens)
        except ValueError:
            raise ValueError(f"META_MAX_OUTPUT_TOKENS must be an integer, got {raw_tokens!r}") from None
        if self.max_output_tokens <= 0:
            raise ValueError("META_MAX_OUTPUT_TOKENS must be positive")
        self.adaptive_output_budget = max_output_tokens is None
        ceiling = max_output_tokens_ceiling if max_output_tokens_ceiling is not None else os.getenv(
            "META_MAX_OUTPUT_TOKENS_CEILING", str(max(32768, self.max_output_tokens)))
        self.max_output_tokens_ceiling = int(ceiling)
        if self.max_output_tokens_ceiling < self.max_output_tokens:
            raise ValueError("META_MAX_OUTPUT_TOKENS_CEILING must be at least META_MAX_OUTPUT_TOKENS")
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        try:
            self.timeout = float(timeout if timeout is not None else os.getenv('META_REQUEST_TIMEOUT_SECONDS', '150'))
        except (ValueError,TypeError):
            raise ValueError('META_REQUEST_TIMEOUT_SECONDS must be a finite positive number') from None
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError('META_REQUEST_TIMEOUT_SECONDS must be a finite positive number')
        self.max_attempts = max_attempts
        self.cache_dir = cache_dir
        self._client = client
        self._sleep = sleep

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise LLMError("config", "MODEL_API_KEY is not configured")
            import openai
            self._client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url,
                                         timeout=self.timeout, max_retries=0)
        return self._client

    def output_budget(self, payload: dict) -> int:
        """Scale the starting allowance with serialized input size, not an exact tokenizer count.

        The configured baseline covers a 2,000-byte payload. At least the baseline
        leaves reasoning/JSON room for short inputs. An explicit constructor budget
        remains an override for callers that know their endpoint's constraints.
        """
        if not self.adaptive_output_budget:
            return self.max_output_tokens
        size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        scaled = (self.max_output_tokens * size + 1999) // 2000
        return min(self.max_output_tokens_ceiling, max(self.max_output_tokens, scaled))

    def _request(self, client, name: str, instructions: str, payload: dict, schema: dict, token_budget: int,
                 temperature=None):
        text_input = json.dumps(payload, ensure_ascii=False)
        sampling = {"temperature": temperature} if temperature is not None else {}
        if self.api_style == "chat":
            resp = client.chat.completions.create(
                model=self.model, max_tokens=token_budget, **sampling,
                messages=[{"role": "system", "content": instructions},
                          {"role": "user", "content": text_input}],
                response_format={"type": "json_schema", "json_schema": {
                    "name": name, "strict": True, "schema": schema}})
            choice = resp.choices[0]
            if choice.finish_reason not in (None, "stop"):
                raise LLMError("incomplete", f"finish_reason={choice.finish_reason}; output budget={token_budget}",
                               usage=usage_from_chat(getattr(resp, "usage", None)), response_id=getattr(resp, "id", None),
                               token_exhausted=choice.finish_reason == "length")
            text = choice.message.content or ""
            return text, getattr(resp, "id", None), usage_from_chat(getattr(resp, "usage", None))
        resp = client.responses.create(
            model=self.model, store=False, max_output_tokens=token_budget, **sampling,
            instructions=instructions, input=text_input,
            text={"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}})
        if getattr(resp, "status", "completed") != "completed":
            reason = getattr(getattr(resp, "incomplete_details", None), "reason", "unknown")
            raise LLMError("incomplete", f"status={resp.status}; reason={reason}; output budget={token_budget}",
                           usage=usage_from_responses(getattr(resp, "usage", None)), response_id=getattr(resp, "id", None),
                           token_exhausted=reason == "max_output_tokens")
        return resp.output_text, getattr(resp, "id", None), usage_from_responses(getattr(resp, "usage", None))

    def _call(self, name: str, instructions: str, payload: dict, schema: dict) -> LLMResult:
        import openai
        client = self._get_client()
        transient = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
                     openai.InternalServerError)
        token_budget = self.output_budget(payload)
        emit(f"model call {name!r}: input-sized output budget {token_budget}")
        request_id = uuid.uuid4().hex[:16]
        request_fields = dict(request_id=request_id, name=name, model=self.model, api_style=self.api_style,
                              timeout_s=self.timeout, max_attempts=self.max_attempts,
                              payload_bytes=len(json.dumps(payload, ensure_ascii=False).encode('utf-8')),
                              instructions_bytes=len(instructions.encode('utf-8')),
                              schema_bytes=len(json.dumps(schema).encode('utf-8')))
        section=payload.get('section')
        request_fields['section_id']=section.get('id') if isinstance(section,dict) else None
        request_fields['chunk_ids']=[c['chunk_id'] for c in (payload.get('chunks') or []) if isinstance(c,dict) and 'chunk_id' in c][:64]
        _request_event('request_start', **request_fields)
        attempts: list[dict] = []
        total_usage: dict[str, int] = {}
        sampling_supported = True
        for attempt in range(1, self.max_attempts + 1):
            if cancel.is_cancelled():
                _request_event('cancelled', **request_fields, attempt=attempt)
                error = LLMError("cancelled", "the tool timed out; no further model calls are made")
                error.attempts = attempts
                raise error
            if attempt > 1:
                token_budget = min((token_budget * 5 + 3) // 4, self.max_output_tokens_ceiling)
                emit(f"model call {name!r} attempt {attempt}/{self.max_attempts}: output budget {token_budget}")
            temperature = (None, 0.1, 0.3, 0.0, 0.2)[attempt - 1] if sampling_supported else None
            attempt_rules = instructions
            if attempt == 5:
                attempt_rules += ("\nRecovery attempt: use short atomic statements and minimal wording. "
                                  "Return only schema-required fields and supported evidence. Keep all original "
                                  "citation, coverage, provenance and safety constraints. Do not invent missing facts.")
            attempt_started = time.perf_counter()
            details = dict(attempt=attempt, timeout_s=self.timeout, output_budget=token_budget,
                           temperature=temperature, recovery_profile='compact' if attempt == 5 else 'standard')
            _request_event('attempt_start', **request_fields, **{k:v for k,v in details.items() if k!='timeout_s'})
            emit(f"model request {request_id} {name!r}: attempt {attempt}/{self.max_attempts}, "
                 f"timeout {self.timeout:g}s, input {request_fields['payload_bytes']} bytes, "
                 f"output allowance {token_budget}, temperature {temperature}")
            def completed(status, **extra):
                result = details | dict(status=status, duration_ms=round((time.perf_counter()-attempt_started)*1000,1)) | extra
                _request_event('attempt_done', **request_fields, **{k:v for k,v in result.items() if k!='timeout_s'})
                return result
            try:
                text, response_id, usage = self._request(client, name, attempt_rules, payload, schema, token_budget, temperature)
                for key, value in usage.items():
                    total_usage[key] = total_usage.get(key, 0) + value
                try:
                    data = json.loads(text)
                    if not isinstance(data, dict):
                        raise ValueError("expected an object")
                except ValueError:
                    raise LLMError("parse", "response was not a JSON object", response_id=response_id) from None
                attempts.append(completed('PASS', response_id=response_id, usage=usage))
                break
            except LLMError as exc:
                attempts.append(completed(exc.kind, response_id=exc.response_id, token_exhausted=exc.token_exhausted))
                for key, value in exc.usage.items():
                    total_usage[key] = total_usage.get(key, 0) + value
                if (not exc.token_exhausted and exc.kind != "parse") or attempt == self.max_attempts:
                    exc.usage, exc.attempts = total_usage, attempts
                    raise
                emit(f"model call {name!r} retrying after {exc.kind} "
                     f"(attempt {attempt + 1}/{self.max_attempts})")
            except transient as exc:
                attempts.append(completed('transient', error_type=type(exc).__name__, cause_types=_error_types(exc),
                                          http_status=getattr(exc,'status_code',None)))
                emit(f"model request {request_id}: {type(exc).__name__} after "
                     f"{attempts[-1]['duration_ms']/1000:.1f}s (timeout {self.timeout:g}s)")
                if attempt == self.max_attempts:
                    error = LLMError("transient", f"{type(exc).__name__} after {attempt} attempts", usage=total_usage)
                    error.attempts = attempts
                    raise error from None
                delay = 2.0 * 2 ** (attempt - 1)
                _request_event('retry_scheduled', **request_fields, attempt=attempt, next_attempt=attempt+1, backoff_s=delay)
                emit(f"model call {name!r} hit {type(exc).__name__}; retrying in {delay:.0f}s "
                     f"(attempt {attempt}/{self.max_attempts})")
                self._sleep(delay)
            except openai.AuthenticationError:
                attempts.append(completed('auth', http_status=401))
                error = LLMError('auth', 'authentication failed'); error.attempts=attempts
                raise error from None
            except openai.APIStatusError as exc:
                if (exc.status_code == 400 and temperature is not None and
                        "temperature" in str(exc).lower() and attempt < self.max_attempts):
                    sampling_supported = False
                    attempts.append(completed('unsupported_temperature', http_status=400))
                    continue
                # Exception text may echo request details; keep only the status code.
                attempts.append(completed('http', http_status=exc.status_code))
                error = LLMError('http', f'status {exc.status_code}'); error.attempts=attempts
                raise error from None
            except BaseException as exc:
                completed('INTERRUPTED' if isinstance(exc,(KeyboardInterrupt,SystemExit)) else 'ERROR', error_type=type(exc).__name__)
                raise
        return LLMResult(data=data, model=self.model, response_id=response_id, usage=total_usage, attempts=attempts)


class FakeLLM(_Base):
    """Offline stand-in: handlers map a call name to a function of the payload."""

    def __init__(self, handlers: dict[str, Callable[[dict], dict]], model: str = "fake-llm",
                 cache_dir: Path | None = None):
        self.handlers = handlers
        self.model = model
        self.cache_dir = cache_dir
        self.calls: list[tuple[str, dict]] = []
        self._lock = threading.Lock()

    def _call(self, name: str, instructions: str, payload: dict, schema: dict) -> LLMResult:
        with self._lock:
            self.calls.append((name, payload))
            response_id = f"fake-{len(self.calls)}"
        return LLMResult(data=self.handlers[name](payload), model=self.model,
                         response_id=response_id)
