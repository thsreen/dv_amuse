import json

from dv_agent.quality import code_notice as cn

PLAN = {"sections": [
    {"id": "checks", "entries": [
        {"provenance": "DOCUMENTED", "cited_chunk_ids": ["CH-1"]},
        {"provenance": "DOCUMENTED", "cited_chunk_ids": ["CH-2"], "cited_req_ids": ["REQ-1"]},
        {"provenance": "DOCUMENTED", "cited_methodology_ids": ["METH-XPROP-1"]},
        {"provenance": "DOCUMENTED"},
        {"provenance": "INFERRED", "cited_chunk_ids": ["CH-1"]},
        {"provenance": "ASSUMED"},
        {"provenance": "INFERRED", "cited_rtl_observation_ids": ["RTLOBS-1"]}]},
    {"id": "configurations", "configurations": [{"provenance": "DOCUMENTED", "cited_chunk_ids": ["CH-3"]}]}]}


def test_counts_follow_what_code_generation_actually_uses():
    c = cn.count_plan_items(PLAN)
    assert c == dict(used=3, inferred=1, assumed=1, uncited_documented=1, rtl_observation=1, methodology=1,
                     total=8, with_requirement_ids=1)


def test_notice_states_what_is_used_excluded_and_how_to_stop(monkeypatch):
    monkeypatch.delenv(cn.ABORT_SECONDS_ENV, raising=False)
    text = "\n".join(cn.code_notice(PLAN))
    assert "only from the 3 of 8 plan entries" in text and "NEEDS_REVIEW" in text
    assert "Not used: 1 inferred, 1 assumed, 1 documented without a citation, 1 RTL observation." in text
    assert "1 entry comes from DV-agent methodology rules" in text and "not used as code facts" in text
    assert "Type /abort and press Enter within 10 s" in text and "Ctrl-C" in text
    chunk_only = {"sections": [{"id": "x", "entries": [{"provenance": "DOCUMENTED", "cited_chunk_ids": ["CH-1"]}]}]}
    assert "no requirement IDs" in "\n".join(cn.code_notice(chunk_only))
    monkeypatch.setenv(cn.ABORT_SECONDS_ENV, "0")
    assert "within" not in "\n".join(cn.code_notice(PLAN)) and "Press Ctrl-C at any time" in "\n".join(cn.code_notice(PLAN))


def test_only_a_real_terminal_waits_for_an_abort(monkeypatch):
    assert cn.abort_requested(interactive=False, seconds=5) is False  # scripted sessions never wait
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr(cn.select, "select", lambda r, w, x, t: (r, [], []))
    for typed, expected in (("/abort\n", True), (" Cancel \n", True), ("/plan\n", False)):
        monkeypatch.setattr("sys.stdin.readline", lambda typed=typed: typed, raising=False)
        assert cn.abort_requested(interactive=True, seconds=5) is expected
    monkeypatch.setattr(cn.select, "select", lambda r, w, x, t: ([], [], []))  # nothing typed within the window
    assert cn.abort_requested(interactive=True, seconds=5) is False


def test_repl_code_shows_the_warning_then_builds_without_asking(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    out = tmp_path / "run"
    (out / "dv").mkdir(parents=True)
    (out / "dv" / "testplan_doc.json").write_text(json.dumps(PLAN))
    monkeypatch.setattr(terminal, "_default_out", lambda: out)
    built = []
    monkeypatch.setattr(terminal, "build_code", lambda *a, **k: built.append(1) or
                        dict(code_dir="c", policy=dict(kept=1, skipped=0), tests=[dict(name="t")]))
    lines = iter(["/code"])
    shown = []
    terminal.repl(input_fn=lambda _p: next(lines, None) or (_ for _ in ()).throw(EOFError), output_fn=shown.append, llm=object())
    assert built == [1] and "--- before code generation ---" in "\n".join(shown)


def test_repl_abort_stops_before_anything_is_built(tmp_path, monkeypatch):
    from orchestrator_agent import repl as terminal
    out = tmp_path / "run"
    (out / "dv").mkdir(parents=True)
    (out / "dv" / "testplan_doc.json").write_text(json.dumps(PLAN))
    monkeypatch.setattr(terminal, "_default_out", lambda: out)
    monkeypatch.setattr(terminal, "abort_requested", lambda **kw: True)
    monkeypatch.setattr(terminal, "build_code", lambda *a, **k: (_ for _ in ()).throw(AssertionError("aborted")))
    lines = iter(["/code"])
    shown = []
    terminal.repl(input_fn=lambda _p: next(lines, None) or (_ for _ in ()).throw(EOFError), output_fn=shown.append, llm=object())
    assert "Code aborted before it started; nothing was generated." in "\n".join(shown)
