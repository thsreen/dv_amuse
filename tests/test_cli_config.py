"""CLI entry points and configuration validation (checklist items: packaging/CLI, llm mode, config errors)."""
import json
import subprocess
import sys

import pytest

from dv_agent import cli
from dv_agent.cli import main
from dv_agent.llm import MetaClient
from dv_agent.pipeline import run_build_graph, run_ingest

COMMANDS = ["ingest", "build-graph", "interfaces", "registers", "strategy", "plan", "testplan", "pipeline", "query", "context", "deps", "features", "usage",
            "lineage", "rtl-interfaces", "build-interface"]


@pytest.mark.parametrize("cmd", COMMANDS)
def test_every_subcommand_has_help(cmd, capsys):
    with pytest.raises(SystemExit) as exc:
        main([cmd, "--help"])
    assert exc.value.code == 0 and "usage: dv-agent" in capsys.readouterr().out


def test_console_entry_point_runs():
    out = subprocess.run([sys.executable, "-m", "dv_agent.cli", "--help"], capture_output=True, text=True)
    assert out.returncode == 0 and "ingest" in out.stdout


class Exploding:
    model = "should-not-be-used"

    def __init__(self, *a, **k):
        raise AssertionError("the API client must not be constructed")


def test_llm_off_never_builds_a_client_even_with_a_key(spec_repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MODEL_API_KEY", "set")
    monkeypatch.setattr(cli, "MetaClient", Exploding)
    monkeypatch.setattr(cli, "MetaEmbedder", Exploding)
    out = tmp_path / "run"
    assert main(["pipeline", str(spec_repo), "--out", str(out), "--llm", "off"]) == 0
    assert json.loads(capsys.readouterr().out)["build"]["llm"]["status"] == "NOT_RUN"


def test_llm_on_without_key_fails_clearly(spec_repo, tmp_path, capsys):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    assert main(["build-graph", "--out", str(out), "--llm", "on"]) == 2
    assert "MODEL_API_KEY is not set" in capsys.readouterr().err
    assert not (out / "graph.json").exists()


def test_llm_auto_without_key_builds_structurally(spec_repo, tmp_path, capsys):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    assert main(["build-graph", "--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "structural"


def test_invalid_llm_mode_env_is_rejected(spec_repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DV_AGENT_LLM_MODE", "maybe")
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    assert main(["build-graph", "--out", str(out)]) == 2
    assert "LLM mode must be one of" in capsys.readouterr().err


def test_meta_client_settings_are_validated(monkeypatch):
    monkeypatch.setenv("META_API_STYLE", "graphql")
    with pytest.raises(ValueError, match="META_API_STYLE"):
        MetaClient(api_key="k")
    monkeypatch.setenv("META_API_STYLE", "chat")
    monkeypatch.setenv("META_MAX_OUTPUT_TOKENS", "lots")
    with pytest.raises(ValueError, match="META_MAX_OUTPUT_TOKENS"):
        MetaClient(api_key="k")
    monkeypatch.setenv("META_MAX_OUTPUT_TOKENS", "2048")
    client = MetaClient(api_key="k")
    assert client.api_style == "chat" and client.max_output_tokens == 2048


def test_bad_or_missing_template_is_a_clear_error(spec_repo, tmp_path, monkeypatch, capsys):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, None)
    monkeypatch.setattr(cli, "_llm", lambda: type("L", (), {"model": "m", "cache_dir": None})())
    assert main(["testplan", "--out", str(out), "--template", str(tmp_path / "nope.json")]) == 2
    assert "template not found" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert main(["testplan", "--out", str(out), "--template", str(bad)]) == 2
    assert "not valid JSON" in capsys.readouterr().err
    bad.write_text(json.dumps({"template_id": "x", "sections": [{"id": "a", "generator": "entries"}]}))
    assert main(["testplan", "--out", str(out), "--template", str(bad)]) == 2
    assert "needs string id and heading" in capsys.readouterr().err
