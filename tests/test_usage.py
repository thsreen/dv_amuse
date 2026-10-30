import json
from types import SimpleNamespace

import pytest

from conftest import dependency_handler, extraction_handler
from dv_agent.cli import main
from dv_agent.core.llm import FakeLLM, usage_from_chat, usage_from_responses
from dv_agent.pipeline import run_build_graph, run_ingest, run_testplan_doc
from dv_agent.core.trace import Tracer
from dv_agent.core.usage import estimate_usage, summarize


def test_usage_includes_reasoning_and_cached_tokens():
    resp = SimpleNamespace(input_tokens=100, output_tokens=40,
                           output_tokens_details=SimpleNamespace(reasoning_tokens=25),
                           input_tokens_details=SimpleNamespace(cached_tokens=60))
    assert usage_from_responses(resp) == dict(input=100, output=40, reasoning=25, cached_input=60)
    chat = SimpleNamespace(prompt_tokens=10, completion_tokens=5, completion_tokens_details=None,
                           prompt_tokens_details=SimpleNamespace(cached_tokens=4))
    assert usage_from_chat(chat) == dict(input=10, output=5, reasoning=0, cached_input=4)
    assert usage_from_responses(None) == {} and usage_from_chat(None) == {}


def test_estimate_is_about_four_characters_per_token():
    u = estimate_usage("x" * 40, {"a": "y" * 36}, {}, {"b": "z" * 30})
    prompt_chars = 40 + len('{"a": "' + "y" * 36 + '"}') + len("{}")
    assert u["input"] == round(prompt_chars / 4) and u["output"] == round(len('{"b": "' + "z" * 30 + '"}') / 4)
    assert u["reasoning"] == u["cached_input"] == 0


class ReportingLLM(FakeLLM):
    """Fake model whose responses report real-looking usage, like the Meta API does."""

    def _call(self, name, instructions, payload, schema):
        result = super()._call(name, instructions, payload, schema)
        result.usage = dict(input=1000, cached_input=400, output=200, reasoning=50)
        return result


def test_counts_split_cached_input_reasoning_and_local_cache(tmp_path):
    llm = ReportingLLM({"step": lambda p: {"ok": 1}}, cache_dir=tmp_path / "cache")
    with Tracer(tmp_path / "t.jsonl", "run") as first:
        llm.structured(name="step", instructions="i", payload={"n": 1}, schema={}, tracer=first)
        llm.structured(name="step", instructions="i", payload={"n": 2}, schema={}, tracer=first)
    with Tracer(tmp_path / "t.jsonl", "run") as second:
        llm.structured(name="step", instructions="i", payload={"n": 1}, schema={}, tracer=second)
    a = summarize(tmp_path / "t.jsonl", first.trace_id)["totals"]
    assert a["calls"] == a["api_calls"] == 2 and a["estimated_calls"] == 0
    assert a["consumed"] == dict(input=2000, cached_input=800, output=400, reasoning=100, uncached_input=1200, total=2400)
    b = summarize(tmp_path / "t.jsonl", second.trace_id)["totals"]
    assert b["local_cache_hits"] == 1 and b["api_calls"] == 0 and b["consumed"]["total"] == 0
    assert b["replayed"]["total"] == 1200 and b["from_scratch"]["input"] == 1000
    both = summarize(tmp_path / "t.jsonl", [first.trace_id, second.trace_id])
    assert both["totals"]["calls"] == 3 and both["by_call"]["step"]["consumed"]["output"] == 400
    assert [r["trace_id"] for r in summarize(tmp_path / "t.jsonl")["runs"]] == [first.trace_id, second.trace_id]


def _llm(out):
    return FakeLLM({"spec_requirements": extraction_handler, "requirement_dependencies": dependency_handler},
                   cache_dir=out / "llm_cache")


def test_command_output_reports_tokens(spec_repo, tmp_path, capsys):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    u = run_build_graph(out, _llm(out), mode="graph")["usage"]
    assert u["api_calls"] > 0 and u["estimated_calls"] == u["calls"] and u["consumed"]["input"] > 0
    again = run_build_graph(out, _llm(out), force=True, mode="graph")["usage"]
    assert again["local_cache_hits"] == u["calls"] and again["consumed"]["total"] == 0
    assert again["from_scratch"]["total"] == u["consumed"]["total"]
    assert main(["usage", "--out", str(out), "--last", "1"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert len(printed["runs"]) == 1 and set(printed["runs"][0]["by_call"]) == {"spec_requirements", "requirement_dependencies"}


def test_final_test_plan_carries_token_usage(spec_repo, tmp_path):
    from test_testplan_doc import _llm as full_llm
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, full_llm(), mode="graph")
    summary = run_testplan_doc(out, full_llm(), mode="graph")
    doc = json.loads((out / "testplan_doc.json").read_text())
    assert set(doc["token_usage"]) == {"Test-plan run", "Graph build"}
    plan_calls = doc["token_usage"]["Test-plan run"]["by_call"]
    assert {"testplan_interfaces", "testplan_registers", "testplan_strategy", "testplan_entries"} <= set(plan_calls)
    assert summary["token_usage"]["Test-plan run"]["consumed"]["total"] > 0
    md = (out / "testplan_doc.md").read_text()
    assert "## Token usage" in md and "| **Total** |" in md and "Cached input" in md


def test_pipeline_totals_cover_only_stages_that_ran(spec_repo, tmp_path, capsys, monkeypatch):
    from dv_agent import cli
    from test_testplan_doc import _llm as full_llm
    monkeypatch.setattr(cli, "_llm", full_llm)
    out = tmp_path / "demo"
    assert main(["pipeline", str(spec_repo), "--out", str(out), "--testplan"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["usage"]["api_calls"] > 0
    assert main(["pipeline", str(spec_repo), "--out", str(out), "--testplan"]) == 0
    assert json.loads(capsys.readouterr().out)["usage"] is None  # everything reused: nothing consumed


def test_repair_calls_are_counted(spec_repo, tmp_path):
    from test_testplan_doc import _llm as full_llm
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, full_llm(), mode="graph")
    summary = run_testplan_doc(out, full_llm(), mode="graph")
    plan = summary["token_usage"]["Test-plan run"]
    assert 0 < plan["repair_calls"] < plan["calls"]  # the flawed fake strategy is refused and repaired
    strategy = json.loads((out / "testplan_doc.json").read_text())["token_usage"]["Test-plan run"]["by_call"]["testplan_strategy"]
    assert strategy["repair_calls"] == 2 and strategy["calls"] == 3
    assert "were repairs after a check refused" in (out / "testplan_doc.md").read_text()
