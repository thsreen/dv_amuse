import pytest

from dv_agent.graph.graph_checkpoint import CheckpointLLM
from dv_agent.core.llm import FakeLLM, LLMError


def test_graph_resume_reuses_success_including_empty_results(tmp_path):
    calls = []
    def handler(payload):
        calls.append(payload["batch"])
        if payload["batch"] == "failed" and calls.count("failed") == 1:
            raise LLMError("transient", "offline failure")
        return {"requirements": []}
    delegate = FakeLLM({"extract": handler})
    def run(client, batch):
        return client.structured(name="extract", instructions="rules", payload={"batch": batch}, schema={})
    client = CheckpointLLM(delegate, tmp_path)
    run(client, "complete")
    with pytest.raises(LLMError):
        run(client, "failed")
    resumed = CheckpointLLM(delegate, tmp_path)
    assert run(resumed, "complete").cached
    assert run(resumed, "failed").data == {"requirements": []}
    assert calls == ["complete", "failed", "failed"]


def test_graph_checkpoint_changes_with_source_or_constraints(tmp_path):
    delegate = FakeLLM({"extract": lambda payload: {"ok": True}})
    client = CheckpointLLM(delegate, tmp_path)
    for text in ("old source", "new source"):
        client.structured(name="extract", instructions="rules", payload={"text": text}, schema={})
    assert len(delegate.calls) == 2


def test_testplan_resume_replays_batches_and_repairs(tmp_path):
    delegate = FakeLLM({"testplan_registers": lambda payload: {"registers": []}})
    for _ in range(2):
        client = CheckpointLLM(delegate, tmp_path, stage="testplan")
        for payload in ({"chunk": "one"}, {"chunk": "one", "refusal": ["missing field"]}):
            client.structured(name="testplan_registers", instructions="rules", payload=payload, schema={})
    assert len(delegate.calls) == 2


def test_embedding_retry_is_bounded_and_uses_no_temperature(monkeypatch):
    from types import SimpleNamespace
    import httpx
    import openai
    from dv_agent.retrieval.dense import MetaEmbedder
    from dv_agent.retrieval import dense
    calls, sleeps = [], []
    def create(**kwargs):
        calls.append(kwargs)
        raise openai.RateLimitError("rate limited", response=httpx.Response(
            429, request=httpx.Request("POST", "https://example.invalid")), body=None)
    monkeypatch.setattr(dense.time, "sleep", sleeps.append)
    embedder = MetaEmbedder(model="embedding", client=SimpleNamespace(embeddings=SimpleNamespace(create=create)))
    with pytest.raises(openai.RateLimitError):
        embedder.embed(["source"])
    assert len(calls) == 5 and sleeps == [2, 4, 8, 16]
    assert all("temperature" not in call for call in calls)
