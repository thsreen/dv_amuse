"""Progress reporting: silent by default, per-step lines on stderr via the CLI."""
import json
import threading
from types import SimpleNamespace

import httpx
import openai
import pytest

from dv_agent import progress
from dv_agent.cli import main
from dv_agent.extract import ExtractConfig, extract_requirements
from dv_agent.graph import build_structure
from dv_agent.ingest import load_chunks, load_manifest
from dv_agent.llm import FakeLLM, LLMError, MetaClient
from dv_agent.pipeline import run_build_graph, run_ingest
from dv_agent.trace import Tracer


@pytest.fixture(autouse=True)
def clean_sink():
    progress.set_sink(None)
    yield
    progress.set_sink(None)


def test_emit_is_silent_without_a_sink(capsys):
    progress.emit("nothing should appear")
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_sink_receives_every_message():
    seen = []
    progress.set_sink(seen.append)
    progress.emit("first")
    progress.emit("second")
    assert seen == ["first", "second"]


def test_extract_requirements_reports_each_chunk(spec_repo, tmp_path, fake_llm):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    G = build_structure(load_manifest(out), load_chunks(out))
    seen = []
    progress.set_sink(seen.append)
    with Tracer(out / "t.jsonl", "t") as tracer:
        stats = extract_requirements(G, fake_llm, tracer)
    total = stats["chunks"]
    assert seen[0].startswith(f"extracting requirements from {total} chunks")
    assert [m for m in seen if m.startswith("[1/") and "chunk CH-" in m]
    assert [m for m in seen if m.startswith(f"[{total}/{total}]")]
    assert seen[-1].startswith("extraction done: ")


def test_build_graph_reports_both_llm_stages(spec_repo, tmp_path, fake_llm):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    seen = []
    progress.set_sink(seen.append)
    run_build_graph(out, fake_llm)
    text = "\n".join(seen)
    assert "extracting requirements from" in text
    assert "extracting dependencies for" in text
    assert "extraction done:" in text and "dependencies done:" in text


def test_pipeline_progress_goes_to_stderr_and_stdout_stays_json(spec_repo, tmp_path, capsys):
    out = tmp_path / "run"
    assert main(["pipeline", str(spec_repo), "--out", str(out), "--llm", "off"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["build"]["llm"]["status"] == "NOT_RUN"
    assert "dv-agent: [1/2] ingest:" in captured.err
    assert "dv-agent: [2/2] build-graph (--llm off, --mode full)" in captured.err
    assert "dv-agent: pipeline done" in captured.err


def test_llm_retry_reports_progress():
    resp = httpx.Response(429, request=httpx.Request("POST", "https://example.invalid/v1/responses"))

    class FakeResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise openai.RateLimitError("boom", response=resp, body=None)
            return SimpleNamespace(status="completed", output_text='{"x": "ok"}', id="resp-1",
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    seen = []
    progress.set_sink(seen.append)
    client = MetaClient(api_key="k", model="m", client=SimpleNamespace(responses=FakeResponses()),
                        sleep=lambda s: None)
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"],
              "additionalProperties": False}
    assert client.structured(name="t", instructions="i", payload={}, schema=schema).data == {"x": "ok"}
    assert seen[0] == "llm call 't' start (model m)"
    retries = [m for m in seen if "retrying in" in m]
    assert len(retries) == 1 and "RateLimitError" in retries[0] and "retrying in 2s" in retries[0]
    assert seen[-1].startswith("llm call 't' done (") and "attempts 2" in seen[-1]


def test_global_sink_reaches_worker_threads():
    seen, guard = [], threading.Lock()

    def capture(message):
        with guard:
            seen.append(message)

    progress.set_global_sink(capture)
    threads = [threading.Thread(target=progress.emit, args=(f"line-{i}",)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    progress.set_global_sink(None)
    assert sorted(seen) == sorted(f"line-{i}" for i in range(16))


def test_thread_local_sink_wins_and_unset_falls_through():
    thread_seen, global_seen = [], []
    progress.set_global_sink(global_seen.append)
    progress.set_sink(thread_seen.append)
    progress.emit("hello")
    assert thread_seen == ["hello"] and global_seen == []
    progress.set_sink(None)
    progress.emit("falls through")
    assert thread_seen == ["hello"] and global_seen == ["falls through"]
    progress.set_global_sink(None)


def test_structured_emits_start_done_and_fail_lines():
    seen = []
    progress.set_sink(seen.append)
    llm = FakeLLM({"ok": lambda payload: {"x": 1}})
    schema = {"type": "object", "properties": {"x": {"type": "integer"}},
              "required": ["x"], "additionalProperties": False}
    llm.structured(name="ok", instructions="i", payload={}, schema=schema)
    assert seen[0] == "llm call 'ok' start (model fake-llm)"
    assert seen[1].startswith("llm call 'ok' done (") and "attempts 0" in seen[1]

    def denied(payload):
        raise LLMError("auth", "simulated")

    llm = FakeLLM({"no": denied})
    with pytest.raises(LLMError):
        llm.structured(name="no", instructions="i", payload={}, schema=schema)
    assert seen[-1].startswith("llm call 'no' failed: auth after ")


def test_parallel_fetch_emits_start_lines(spec_repo, tmp_path, fake_llm):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    G = build_structure(load_manifest(out), load_chunks(out))
    seen = []
    progress.set_global_sink(seen.append)
    with Tracer(out / "t.jsonl", "t") as tracer:
        extract_requirements(G, fake_llm, tracer, ExtractConfig(max_workers=4))
    progress.set_global_sink(None)
    starts = [m for m in seen if m.startswith("fetch chunk CH-") and "start [dv_extract_" in m]
    assert starts, seen
    assert any("attempts" in m and m.startswith("llm call 'spec_requirements' done") for m in seen)


def test_build_graph_emits_config_line(spec_repo, tmp_path, fake_llm):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    seen = []
    progress.set_sink(seen.append)
    run_build_graph(out, fake_llm, ExtractConfig(max_workers=4))
    assert "build config: model fake-llm, workers 4" in seen
