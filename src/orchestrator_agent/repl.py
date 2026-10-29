"""Four-command interactive path: plan, documented code, basic run, regression."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .actions import build_code, run_tests
from .flow import load_flow
from .repo_intake import find_repo, inspect_repo
from .runner import REVIEW_FILE, run_flow
from .tui import Dashboard

ASK_FILE = "orchestrator_ask.json"
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
HELP = "Commands: /plan  /code  /run  /regress  (Ctrl-D to leave)"


def _builtin_flow() -> Path:
    return Path(__file__).resolve().parent / "flows" / "testplan_flow.json"


def _default_out() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return PACKAGE_ROOT / "runs" / f"orch-{stamp}"


def ask_card(flow: dict, flow_path: Path, variables: dict, requirement: str,
             out: Path, approvals: list[str] | None = None, scan: dict | None = None) -> str:
    descriptions = {
        "dv_ingest": "Read specification files and create citable source chunks.",
        "dv_build_graph": "Extract requirements and their relationships into an evidence graph.",
        "rtl_extract": "Read the top RTL module and build its JSON port interface.",
        "rtl_build_graph": "Analyze connected RTL modules, clocks, resets and dependencies.",
        "dv_testplan": "Recover registers and configurable controls, write the verification strategy and RTL observations, then save JSON, Markdown and HTML testplans.",
    }
    lines = ["--- testplan preview ---", f"request: {requirement or '(describe a design repository)'}",
             f"repository: {variables.get('repo', '(not identified)')}"]
    if scan:
        lines += [f"scanned: {len(scan['specs'])} specification candidate(s), {len(scan['rtl_files'])} RTL module file(s)",
                  f"RTL top: {scan['top'] or '(not identified)'}"]
        lines += [f"note: {note}" for note in scan["notes"]]
    lines.append("/plan will:")
    for i, step in enumerate(flow["steps"], 1):
        lines.append(f"  {i}. {descriptions.get(step['tool'], step.get('description', step['tool']))}")
    lines += [f"output: {out / 'dv' / 'testplan_doc.md'} and testplan_doc.html",
              "Then /code builds only cited DOCUMENTED plan items and a basic smoke test.",
              "/run executes the basic built test; /regress executes every built test.",
              f"ready: {'yes' if scan and scan['specs'] and variables.get('repo') and variables.get('rtl_files') and variables.get('rtl_graph_files') and variables.get('rtl_top') else 'no — name a local repository with specifications, RTL and a clear top module'}"]
    return "\n".join(lines)


def repl(*, llm_mode: str | None = None, input_fn=None, output_fn=None,
         registry: dict | None = None, llm=None, embedder=None,
         dashboard: bool | None = None) -> int:
    read = input_fn if input_fn is not None else input
    show = output_fn if output_fn is not None else print
    interactive = output_fn is None and sys.stdout.isatty()
    use_dashboard = interactive if dashboard is None else dashboard
    mode = (llm_mode or "auto").strip().lower()
    flow_path = _builtin_flow()
    flow = load_flow(flow_path)
    out = _default_out()
    variables: dict = {"include": [], "scope": ""}
    requirement = ""
    scan = None
    show("Describe the design and local repository. I will scan it and show the testplan steps.")
    show(HELP)

    def models():
        nonlocal llm, embedder
        if llm is None and mode != "off":
            from .cli import _models_for
            llm, embedder = _models_for(mode)
        return llm, embedder

    def plan():
        if not scan or not scan["specs"] or not all(variables.get(k) for k in ("repo", "rtl_files", "rtl_graph_files", "rtl_top")):
            show("Name a local repository with specification and RTL files first.")
            return False
        try:
            use_llm, use_embedder = models()
        except ValueError as exc:
            show(f"Plan blocked: {exc}")
            return False
        if use_llm is None:
            show("Plan blocked: MODEL_API_KEY is required for a specification-grounded testplan.")
            return False
        out.mkdir(parents=True, exist_ok=True)
        ask = dict(requirement=requirement, flow=str(flow_path), out=str(out), variables=variables)
        (out / ASK_FILE).write_text(json.dumps(ask, indent=2), encoding="utf-8")
        dash = Dashboard(out, show, flow=flow, title=requirement, ansi=interactive) if use_dashboard else None
        result = run_flow(flow_path, out_dir=out, variables=dict(variables), llm=use_llm,
                          embedder=use_embedder, registry=registry,
                          event_sink=dash.handle if dash else None)
        show(f"Plan: {result['status']} — {result['reason']}")
        if (out / "dv" / "testplan_doc.json").is_file():
            show(f"Testplan: {out / 'dv' / 'testplan_doc.md'}")
            show(f"Readable copy: {out / 'dv' / 'testplan_doc.html'}")
        if result["status"] != "PASS":
            show(f"Review details: {out / REVIEW_FILE}")
        return result["status"] == "PASS"

    while True:
        try:
            line = read("orch> ").strip()
        except (EOFError, KeyboardInterrupt):
            show("")
            return 0
        if not line:
            continue
        if not line.startswith("/"):
            requirement = line
            repo = find_repo(line, PACKAGE_ROOT)
            if repo is not None:
                try:
                    scan = inspect_repo(repo)
                    variables = dict(include=[], scope="", repo=str(scan["repo"]),
                                     rtl_files=[str(scan["top_file"])] if scan["top_file"] else [],
                                     rtl_graph_files=[str(p) for p in scan["rtl_files"]],
                                     rtl_top=scan["top"])
                except (OSError, ValueError) as exc:
                    scan = None
                    show(f"Repository scan failed: {exc}")
            show(ask_card(flow, flow_path, variables, requirement, out, scan=scan))
            continue
        if line == "/plan":
            plan()
        elif line == "/code":
            if not (out / "dv" / "testplan_doc.json").is_file():
                show("No saved testplan; generating it first.")
                plan()
            if not (out / "dv" / "testplan_doc.json").is_file():
                show("Code blocked: no testplan was generated.")
                continue
            try:
                result = build_code(out, variables)
                policy = result["policy"]
                show(f"Code: {result['code_dir']} ({policy['kept']} documented items retained as code input; "
                     f"{policy['skipped']} unsupported or inferred items excluded).")
                show(f"Built tests: {', '.join(t['name'] for t in result['tests'])}. "
                     "Functional checks require reviewed implementation; the basic test is a compile/clock/reset smoke test.")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                show(f"Code blocked: {exc}")
        elif line in ("/run", "/regress"):
            try:
                result = run_tests(out, regress=line == "/regress")
                for test in result["tests"]:
                    show(f"{test['name']}: {test['status']} — {test['reason']}"
                         + (f" ({test['log']})" if test.get("log") else ""))
                show(f"{line[1:]}: {result['status']}")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                show(f"{line[1:]} blocked: {exc}")
        else:
            show(HELP)
