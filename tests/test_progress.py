"""Progress reporting: silent by default, per-step lines on stderr via the CLI."""
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from dv_agent import progress
from dv_agent.cli import main
from dv_agent.extract import extract_requirements
from dv_agent.graph import build_structure
from dv_agent.ingest import load_chunks, load_manifest
from dv_agent.llm import MetaClient
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
    assert "dv-agent: [2/2] build-graph (--llm off)" in captured.err
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
    assert len(seen) == 1 and "RateLimitError" in seen[0] and "retrying in 2s" in seen[0]
