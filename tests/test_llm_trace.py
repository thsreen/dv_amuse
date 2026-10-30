from types import SimpleNamespace

import httpx
import openai
import pytest

from dv_agent.core.llm import LLMError, MetaClient
from dv_agent.core.trace import Tracer, read_trace

SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"],
          "additionalProperties": False}


class FakeResponses:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(status="completed", output_text=outcome, id="resp-1",
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def _client(outcomes):
    return SimpleNamespace(responses=FakeResponses(outcomes))


def _status_error(cls, code):
    resp = httpx.Response(code, request=httpx.Request("POST", "https://example.invalid/v1/responses"))
    return cls("boom", response=resp, body=None)


def _call(client, **kw):
    return client.structured(name="t", instructions="i", payload={"p": 1}, schema=SCHEMA, **kw)


def test_structured_call_uses_strict_schema_and_caches(tmp_path):
    fake = _client(['{"x": "ok"}'])
    client = MetaClient(api_key="k", model="m", client=fake, cache_dir=tmp_path)
    first = _call(client)
    assert first.data == {"x": "ok"} and not first.cached and first.usage == {"input": 10, "output": 5, "reasoning": 0, "cached_input": 0}
    fmt = fake.responses.calls[0]["text"]["format"]
    assert fmt["strict"] is True and fmt["schema"] == SCHEMA
    assert fake.responses.calls[0]["store"] is False
    second = _call(client)
    assert second.cached and second.data == {"x": "ok"} and len(fake.responses.calls) == 1


def test_transient_errors_retry_with_backoff():
    sleeps = []
    fake = _client([_status_error(openai.RateLimitError, 429), '{"x": "ok"}'])
    client = MetaClient(api_key="k", model="m", client=fake, sleep=sleeps.append)
    assert _call(client).data == {"x": "ok"}
    assert sleeps == [2.0]


def test_errors_are_classified_without_leaking_details():
    client = MetaClient(api_key="k", model="m", client=_client(
        [_status_error(openai.AuthenticationError, 401)]))
    with pytest.raises(LLMError) as exc:
        _call(client)
    assert exc.value.kind == "auth"
    client = MetaClient(api_key="k", model="m", client=_client(["not json"] * 5))
    with pytest.raises(LLMError) as exc:
        _call(client)
    assert exc.value.kind == "parse"
    with pytest.raises(LLMError) as exc:
        _call(MetaClient(api_key="", model="m"))
    assert exc.value.kind == "config"


def test_fifth_retry_changes_sampling_and_recovery_instructions():
    fake = _client(["not json"] * 4 + ['{"x":"ok"}'])
    client = MetaClient(api_key="k", model="m", client=fake)
    result = _call(client)
    calls = fake.responses.calls
    assert len(calls) == 5
    assert [c.get("temperature") for c in calls] == [None, 0.1, 0.3, 0.0, 0.2]
    assert [c["max_output_tokens"] for c in calls] == [8192, 10240, 12800, 16000, 20000]
    assert "Recovery attempt" in calls[4]["instructions"]
    assert len(result.attempts) == 5 and result.attempts[0]["status"] == "parse"


def test_request_budget_scales_with_input_and_respects_ceiling(monkeypatch):
    monkeypatch.setenv("META_MAX_OUTPUT_TOKENS", "8192")
    monkeypatch.setenv("META_MAX_OUTPUT_TOKENS_CEILING", "32768")
    fake = _client(['{"x":"ok"}'] * 3)
    client = MetaClient(api_key="k", model="m", client=fake)
    for length in (100, 2000, 20000):
        client.structured(name="chunk", instructions="rules", payload={"text": "x" * length}, schema=SCHEMA)
    budgets = [c["max_output_tokens"] for c in fake.responses.calls]
    assert budgets[0] == 8192 < budgets[1] < budgets[2] == 32768
    assert client.max_output_tokens == 8192


def test_tracer_nests_spans_and_records_errors(tmp_path):
    sink = tmp_path / "t.jsonl"
    with Tracer(sink, "run") as tracer:
        with tracer.span("outer") as outer:
            with tracer.span("inner") as inner:
                inner.update(output={"v": 1})
        with pytest.raises(ValueError):
            with tracer.span("bad"):
                raise ValueError("x")
    recs = {r["name"]: r for r in read_trace(sink)}
    assert recs["inner"]["parent_id"] == outer.id
    assert recs["outer"]["parent_id"] == tracer.root.id
    assert recs["bad"]["level"] == "ERROR"
    assert {r["trace_id"] for r in recs.values()} == {tracer.trace_id}
    assert not tracer.langfuse_active


class FakeObs:
    def __init__(self, log, name):
        self.id = f"lf-{name}"
        self.log = log

    def update(self, **kw):
        self.log.append(("update", self.id, kw))


class FakeLangfuse:
    def __init__(self, fail_on=None):
        self.log, self.fail_on = [], fail_on

    def start_as_current_observation(self, **kw):
        if kw["name"] == self.fail_on:
            raise RuntimeError("network down")
        self.log.append(("start", kw))
        log, name = self.log, kw["name"]

        class CM:
            def __enter__(self_inner):
                return FakeObs(log, name)

            def __exit__(self_inner, *a):
                log.append(("end", name))
        return CM()

    def flush(self):
        self.log.append(("flush",))

    def get_trace_url(self, trace_id):
        return f"https://langfuse.invalid/trace/{trace_id}"


def test_langfuse_mirror_and_failure_isolation(tmp_path):
    lf = FakeLangfuse()
    with Tracer(tmp_path / "t.jsonl", "run", client=lf) as tracer:
        with tracer.span("step", as_type="retriever") as span:
            span.update(output={"ok": True})
    starts = [e[1] for e in lf.log if e[0] == "start"]
    assert starts[0]["trace_context"] == {"trace_id": tracer.trace_id}
    assert starts[1]["as_type"] == "retriever" and span.id == "lf-step"
    assert ("flush",) in lf.log and tracer.trace_url().endswith(tracer.trace_id)

    broken = FakeLangfuse(fail_on="step")
    with Tracer(tmp_path / "t2.jsonl", "run", client=broken) as tracer:
        with tracer.span("step"):
            pass
        assert not tracer.langfuse_active and "failed" in tracer.langfuse_error
    assert [r["name"] for r in read_trace(tmp_path / "t2.jsonl")] == ["step", "run"]


def _response(status, *, reason=None, text='{"x":"ok"}'):
    return SimpleNamespace(status=status, incomplete_details=SimpleNamespace(reason=reason),
                           output_text=text, id="response", usage=SimpleNamespace(input_tokens=10, output_tokens=20))


class SequenceResponses:
    def __init__(self, *items):
        self.items, self.calls = list(items), []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.items.pop(0)


def test_token_exhaustion_grows_budget_and_accounts_for_failed_attempt(tmp_path):
    from dv_agent.core.usage import run_totals
    fake = SequenceResponses(_response("incomplete", reason="max_output_tokens"), _response("completed"))
    client = MetaClient(api_key="k", model="m", client=SimpleNamespace(responses=fake),
                        max_output_tokens=64, max_output_tokens_ceiling=128)
    with Tracer(tmp_path / "t.jsonl", "run") as tracer:
        assert _call(client, tracer=tracer).data == {"x": "ok"}
    assert [c["max_output_tokens"] for c in fake.calls] == [64, 80]
    totals = run_totals(tmp_path / "t.jsonl", tracer.trace_id)
    assert totals["api_calls"] == 2
    assert totals["consumed"]["input"] == 20 and totals["consumed"]["output"] == 40
    assert client.max_output_tokens == 64  # Later small calls start at their original budget.


@pytest.mark.parametrize("reason,expected_calls", [("max_output_tokens", 5), ("content_filter", 1)])
def test_token_retries_are_bounded_and_other_incomplete_responses_are_not_retried(reason, expected_calls, tmp_path):
    fake = SequenceResponses(*[_response("incomplete", reason=reason) for _ in range(5)])
    client = MetaClient(api_key="k", model="m", client=SimpleNamespace(responses=fake),
                        max_output_tokens=64, max_output_tokens_ceiling=128)
    with pytest.raises(LLMError) as error:
        _call(client)
    assert len(fake.calls) == expected_calls and error.value.kind == "incomplete"
    assert reason in str(error.value)
    assert error.value.usage["output"] == 20 * expected_calls


def test_chat_length_limit_uses_the_same_budget_recovery():
    def chat(reason):
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=reason, message=SimpleNamespace(content='{"x":"ok"}'))],
                               id="chat", usage=SimpleNamespace(prompt_tokens=3, completion_tokens=10))
    fake = SequenceResponses(chat("length"), chat("stop"))
    client = MetaClient(api_key="k", model="m", api_style="chat", max_output_tokens=64,
                        max_output_tokens_ceiling=128,
                        client=SimpleNamespace(chat=SimpleNamespace(completions=fake)))
    assert _call(client).data == {"x": "ok"}
    assert [c["max_tokens"] for c in fake.calls] == [64, 80]


def test_partial_extraction_does_not_report_a_passing_graph(spec_repo, tmp_path, fake_llm):
    from dv_agent.pipeline import run_ingest, run_build_graph
    def fail(payload):
        raise LLMError("incomplete", "token limit")
    fake_llm.handlers["spec_requirements"] = fail
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    result = run_build_graph(out, fake_llm, mode="graph")
    assert result["requirements"]["failed_chunks"]
    assert result["llm"]["status"] == "BLOCKED"


def test_default_and_configurable_request_timeout(monkeypatch):
    monkeypatch.delenv('META_REQUEST_TIMEOUT_SECONDS', raising=False)
    assert MetaClient(api_key='k').timeout == 150
    monkeypatch.setenv('META_REQUEST_TIMEOUT_SECONDS','180')
    assert MetaClient(api_key='k').timeout == 180
    assert MetaClient(api_key='k',timeout=150).timeout == 150
    for value in ('0','-1','nan','inf'):
        monkeypatch.setenv('META_REQUEST_TIMEOUT_SECONDS',value)
        with pytest.raises(ValueError): MetaClient(api_key='k')


def test_attempt_logging_is_immediate_detailed_and_sanitized(tmp_path):
    import json
    from dv_agent.graph.graph_checkpoint import CheckpointLLM
    path=tmp_path/'llm_requests.jsonl'
    request=httpx.Request('POST','https://example.invalid')
    secret='private-provider-body'
    outcomes=[openai.APITimeoutError(request=request), '{"x":"ok"}']
    fake=_client(outcomes)
    original=fake.responses.create
    def create(**kwargs):
        records=[json.loads(line) for line in path.read_text().splitlines()]
        assert records[-1]['event']=='attempt_start'
        assert records[-1]['timeout_s']==150
        return original(**kwargs)
    fake.responses.create=create
    llm=MetaClient(api_key=secret,model='m',client=fake,sleep=lambda seconds:None)
    wrapper=CheckpointLLM(llm,tmp_path/'cache',stage='testplan')
    with Tracer(tmp_path/'trace.jsonl','run') as tracer:
        _call(wrapper,tracer=tracer)
        _call(wrapper,tracer=tracer)
    records=[json.loads(line) for line in path.read_text().splitlines()]
    assert [r['event'] for r in records]==['request_start','attempt_start','attempt_done','retry_scheduled',
                                          'attempt_start','attempt_done','cache_hit']
    failed=records[2]
    assert failed['error_type']=='APITimeoutError' and failed['duration_ms']>=0
    assert failed['payload_bytes']>0 and failed['schema_bytes']>0 and failed['instructions_bytes']>0
    assert records[3]['backoff_s']==2 and records[5]['response_id']=='resp-1'
    assert records[2]['request_id']==records[5]['request_id']
    assert secret not in path.read_text()


def test_interruption_is_logged_in_request_and_trace(tmp_path):
    import json
    fake=_client([])
    def interrupted(**kwargs): raise KeyboardInterrupt()
    fake.responses.create=interrupted
    llm=MetaClient(api_key='k',model='m',client=fake)
    with pytest.raises(KeyboardInterrupt):
        with Tracer(tmp_path/'trace.jsonl','run') as tracer: _call(llm,tracer=tracer)
    events=[json.loads(line) for line in (tmp_path/'llm_requests.jsonl').read_text().splitlines()]
    assert events[-1]['status']=='INTERRUPTED' and events[-1]['error_type']=='KeyboardInterrupt'
    spans=read_trace(tmp_path/'trace.jsonl')
    assert all(s['level']=='ERROR' and s['status_message']=='KeyboardInterrupt' for s in spans)
