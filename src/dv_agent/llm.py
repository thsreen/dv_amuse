"""Meta Model API client with strict JSON-schema output, bounded retries, and a response cache.

The API contract (Responses API at META_BASE_URL) follows old_reference/silicon-copilot and is
not yet verified live in this workspace. META_API_STYLE=chat switches to chat.completions.
"""
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .fsutil import atomic_write_text
from .trace import Tracer
from .usage import estimate_usage

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
API_STYLES = ("responses", "chat")


class LLMError(RuntimeError):
    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind = kind


@dataclass
class LLMResult:
    data: dict
    model: str
    response_id: str | None = None
    cached: bool = False
    usage: dict = field(default_factory=dict)


class LLM(Protocol):
    model: str

    def structured(self, *, name: str, instructions: str, payload: dict, schema: dict,
                   tracer: Tracer | None = None) -> LLMResult: ...


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


class _Base:
    model: str
    cache_dir: Path | None

    def _call(self, name: str, instructions: str, payload: dict, schema: dict) -> LLMResult:
        raise NotImplementedError

    def structured(self, *, name: str, instructions: str, payload: dict, schema: dict,
                   tracer: Tracer | None = None) -> LLMResult:
        key = _cache_key(self.model, name, instructions, payload, schema)
        cache_file = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if tracer is None:
            return self._cached_call(cache_file, name, instructions, payload, schema)
        with tracer.span(f"llm:{name}", as_type="generation", model=self.model,
                         input={"instructions": instructions, "payload": payload},
                         metadata={"cache_key": key}) as span:
            result = self._cached_call(cache_file, name, instructions, payload, schema)
            usage = result.usage or estimate_usage(instructions, payload, schema, result.data)
            span.update(output=result.data, usage=usage,
                        metadata={"cached": result.cached, "response_id": result.response_id,
                                  "usage_estimated": not result.usage})
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
                 model: str | None = None, api_style: str | None = None, timeout: float = 90.0,
                 max_attempts: int = 3, max_output_tokens: int | None = None,
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
        self.timeout = timeout
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

    def _request(self, client, name: str, instructions: str, payload: dict, schema: dict):
        text_input = json.dumps(payload, ensure_ascii=False)
        if self.api_style == "chat":
            resp = client.chat.completions.create(
                model=self.model, max_tokens=self.max_output_tokens,
                messages=[{"role": "system", "content": instructions},
                          {"role": "user", "content": text_input}],
                response_format={"type": "json_schema", "json_schema": {
                    "name": name, "strict": True, "schema": schema}})
            choice = resp.choices[0]
            if choice.finish_reason not in (None, "stop"):
                raise LLMError("incomplete", f"finish_reason={choice.finish_reason}")
            text = choice.message.content or ""
            return text, getattr(resp, "id", None), usage_from_chat(getattr(resp, "usage", None))
        resp = client.responses.create(
            model=self.model, store=False, max_output_tokens=self.max_output_tokens,
            instructions=instructions, input=text_input,
            text={"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}})
        if getattr(resp, "status", "completed") != "completed":
            raise LLMError("incomplete", f"status={resp.status}")
        return resp.output_text, getattr(resp, "id", None), usage_from_responses(getattr(resp, "usage", None))

    def _call(self, name: str, instructions: str, payload: dict, schema: dict) -> LLMResult:
        import openai
        client = self._get_client()
        transient = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
                     openai.InternalServerError)
        for attempt in range(1, self.max_attempts + 1):
            try:
                text, response_id, usage = self._request(client, name, instructions, payload, schema)
                break
            except transient as exc:
                if attempt == self.max_attempts:
                    raise LLMError("transient", f"{type(exc).__name__} after {attempt} attempts")
                self._sleep(2.0 * 2 ** (attempt - 1))
            except openai.AuthenticationError:
                raise LLMError("auth", "authentication failed") from None
            except openai.APIStatusError as exc:
                # Exception text may echo request details; keep only the status code.
                raise LLMError("http", f"status {exc.status_code}") from None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise LLMError("parse", "response was not valid JSON") from None
        if not isinstance(data, dict):
            raise LLMError("parse", "response JSON was not an object")
        return LLMResult(data=data, model=self.model, response_id=response_id, usage=usage)


class FakeLLM(_Base):
    """Offline stand-in: handlers map a call name to a function of the payload."""

    def __init__(self, handlers: dict[str, Callable[[dict], dict]], model: str = "fake-llm",
                 cache_dir: Path | None = None):
        self.handlers = handlers
        self.model = model
        self.cache_dir = cache_dir
        self.calls: list[tuple[str, dict]] = []

    def _call(self, name: str, instructions: str, payload: dict, schema: dict) -> LLMResult:
        self.calls.append((name, payload))
        return LLMResult(data=self.handlers[name](payload), model=self.model,
                         response_id=f"fake-{len(self.calls)}")
