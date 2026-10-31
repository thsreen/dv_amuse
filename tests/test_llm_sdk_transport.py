"""MetaClient through the real OpenAI SDK, with a scripted HTTP transport instead of a network."""
import json

import httpx
import openai
import pytest

from dv_agent.core.llm import LLMError, MetaClient

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["x"], "properties": {"x": {"type": "string"}}}


def responses_body(text: str, status: str = "completed", reason: str | None = None) -> dict:
    return {"id": "resp_1", "object": "response", "created_at": 0, "model": "m", "status": status,
            "incomplete_details": {"reason": reason} if reason else None, "parallel_tool_calls": False,
            "tool_choice": "auto", "tools": [],
            "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 3}}}


def client_for(handler, **kw) -> MetaClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    sdk = openai.OpenAI(api_key="test-key", base_url="https://api.meta.test/v1", http_client=http, max_retries=0)
    return MetaClient(client=sdk, api_key="test-key", model="muse-test", sleep=lambda _s: None, **kw)


def test_request_shape_matches_the_documented_responses_contract():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(path=request.url.path, auth=request.headers["authorization"], body=json.loads(request.content))
        return httpx.Response(200, json=responses_body('{"x": "ok"}'))

    result = client_for(handler).structured(name="demo", instructions="be brief", payload={"q": 1}, schema=SCHEMA)
    assert result.data == {"x": "ok"} and result.usage == dict(input=11, output=7, reasoning=3, cached_input=0)
    body = seen["body"]
    assert seen["path"] == "/v1/responses" and seen["auth"] == "Bearer test-key"
    assert body["model"] == "muse-test" and body["store"] is False and body["instructions"] == "be brief"
    assert json.loads(body["input"]) == {"q": 1}
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["name"] == "demo" and fmt["schema"] == SCHEMA
    assert body["max_output_tokens"] > 0


def test_rate_limit_and_server_errors_are_retried_with_the_real_sdk_exceptions():
    statuses = iter([429, 500, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return (httpx.Response(200, json=responses_body('{"x": "after retries"}')) if status == 200
                else httpx.Response(status, json={"error": {"message": "slow down", "type": "x"}}))

    result = client_for(handler).structured(name="demo", instructions="i", payload={}, schema=SCHEMA)
    assert result.data == {"x": "after retries"} and [a["status"] for a in result.attempts] == ["transient", "transient", "PASS"]


def test_token_exhaustion_retries_with_a_larger_budget():
    budgets = []

    def handler(request: httpx.Request) -> httpx.Response:
        budgets.append(json.loads(request.content)["max_output_tokens"])
        if len(budgets) == 1:
            return httpx.Response(200, json=responses_body("", status="incomplete", reason="max_output_tokens"))
        return httpx.Response(200, json=responses_body('{"x": "fits"}'))

    result = client_for(handler).structured(name="demo", instructions="i", payload={}, schema=SCHEMA)
    assert result.data == {"x": "fits"} and budgets[1] > budgets[0]


def test_authentication_failure_is_not_retried_and_leaks_nothing():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, json={"error": {"message": "bad key test-key", "type": "auth"}})

    with pytest.raises(LLMError) as caught:
        client_for(handler).structured(name="demo", instructions="i", payload={}, schema=SCHEMA)
    assert caught.value.kind == "auth" and len(calls) == 1 and "test-key" not in str(caught.value)
