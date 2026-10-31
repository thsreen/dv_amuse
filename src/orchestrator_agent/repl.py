"""Four-command interactive path: plan, documented code, basic run, regression."""
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dv_agent.quality.code_notice import abort_requested, code_notice
from dv_agent.report.testplan_viewer import create_report_server

from .actions import build_code, run_tests
from .assist import explain_run, interpret, rerun_help, rerun_plan, show_text, status_text, validate_text
from .flow import load_flow
from .repo_intake import find_repo, inspect_repo
from .runner import ASK_FILE, REVIEW_FILE, run_flow, run_single_tool
from .tui import Dashboard, testplan_substeps
from .saved_runs import latest_successful, matches_current_run
from .code_run import execute as execute_code, preview as code_preview

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
HELP = "Commands: /plan  /code  /run  /regress  /fresh  (Ctrl-D to leave)"


def _builtin_flow() -> Path:
    return Path(__file__).resolve().parent / "flows" / "testplan_flow.json"


def _rtl_derived_flow() -> Path:
    return Path(__file__).resolve().parent / "flows" / "rtl_derived_testplan_flow.json"


def _asks_for_rtl_spec(prompt: str) -> bool:
    return bool(re.search(r"\brtl\b.{0,50}\b(?:specification|spec)\b|\b(?:specification|spec)\b.{0,50}\b(?:from|using|derived from)\s+rtl\b",
                          prompt, re.I))


def _default_out() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = PACKAGE_ROOT / "runs" / f"orch-{stamp}"
    if not base.exists():
        return base
    suffix = 2
    while True:
        candidate = base.with_name(f"{base.name}-{suffix}")
        if not candidate.exists():
            return candidate
        suffix += 1


def ask_card(flow: dict, flow_path: Path, variables: dict, requirement: str,
             out: Path, approvals: list[str] | None = None, scan: dict | None = None) -> str:
    descriptions = {
        "dv_ingest": "Read specification files and create citable source chunks.",
        "dv_build_graph": "Extract requirements and their relationships into an evidence graph.",
        "rtl_extract": "Read the top RTL module and build its JSON port interface.",
        "rtl_build_graph": "Analyze connected RTL modules, clocks, resets and dependencies.",
        "rtl_build_spec": "Draft a UART-inspired specification from RTL; all claims need RTL engineer review.",
        "dv_testplan": "Recover registers and configurable controls, write the verification strategy and RTL observations, then save JSON, Markdown and HTML testplans.",
    }
    lines = ["--- testplan preview ---", f"request: {requirement or '(describe a design repository)'}",
             f"repository: {variables.get('repo', '(not identified)')}"]
    if scan:
        lines += [f"scanned: {len(scan['specs'])} specification candidate(s), {len(scan['rtl_files'])} RTL module file(s)",
                  f"RTL top: {scan['top'] or '(not identified)'}"]
        lines += [f"note: {note}" for note in scan["notes"]]
    lines.append("/plan will:")
    lines.append("  1. Send startup notification to Hermes/Telegram.")
    for i, step in enumerate(flow["steps"], 2):
        lines.append(f"  {i}. {descriptions.get(step['tool'], step.get('description', step['tool']))}")
        if step["tool"] == "dv_testplan":
            for subid, label in testplan_substeps():
                lines.append(f"     - {label}")
    derived = any(s["tool"] == "rtl_build_spec" for s in flow["steps"])
    ready = bool(scan and (scan["specs"] or derived) and variables.get("repo") and
                 variables.get("rtl_files") and variables.get("rtl_graph_files") and variables.get("rtl_top"))
    lines += [f"output: {out / 'dv' / 'testplan_doc.md'} and testplan_doc.html",
              *( [f"inferred RTL specification: {out / 'rtl_spec' / 'doc' / 'rtl_derived_spec.md'}",
                  "All draft-derived checks remain INFERRED and require RTL engineer validation."] if derived else []),
              "Then /code builds only cited DOCUMENTED plan items (it warns first; /abort stops it).",
              "/run executes the basic built test; /regress executes every built test.",
              f"ready: {'yes' if ready else 'no — name a local repository with RTL and a clear top module'}"]
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
    issued_dirs = {out}
    variables: dict = {"include": [], "scope": ""}
    requirement = ""
    scan = None
    viewer = None
    viewer_thread = None
    restore_saved = True

    def fresh_out() -> Path:
        """A run directory unused by this session and absent on disk."""
        candidate = _default_out()
        match = re.search(r"-(\d+)$", candidate.name)
        stem, num = (candidate.name[:match.start()], int(match.group(1))) \
            if match else (candidate.name, 1)
        while candidate in issued_dirs or candidate.exists():
            num += 1
            candidate = candidate.with_name(f"{stem}-{num}")
        issued_dirs.add(candidate)
        return candidate
    show("Describe the design and local repository. I will scan it and show the testplan steps.")
    show(HELP)
    if os.getenv("DV_AGENT_MODE", "basic") == "basic":
        show("Basic RAG demo: direct source retrieval, no model requirement/dependency graph; target 10–15 minutes.")

    def models():
        nonlocal llm, embedder
        if llm is None and mode != "off":
            from .cli import _models_for
            llm, embedder = _models_for(mode)
        return llm, embedder

    def show_viewer() -> None:
        nonlocal viewer, viewer_thread
        report = out / "dv"
        if not (report / "testplan_doc.html").is_file():
            return
        runs_root = PACKAGE_ROOT / "runs"
        root = runs_root if report.resolve().is_relative_to(runs_root.resolve()) else out
        if viewer is None:
            try:
                viewer = create_report_server(root, port=0)
            except ValueError as exc:
                show(f"Local viewer unavailable: {exc}")
                show(f"For the polished testplan, open the HTML file: {report / 'testplan_doc.html'}")
                return
            viewer_thread = threading.Thread(target=viewer.serve_forever,
                                             name="orchestrator-testplan-viewer", daemon=True)
            viewer_thread.start()
        plan_id = report.relative_to(root).as_posix()
        url = f"http://127.0.0.1:{viewer.server_port}/?plan={quote(plan_id, safe='')}"
        show(f"For the polished testplan, open: {url}")
        show(f"HTML file: {report / 'testplan_doc.html'}")
        show(f"Editable Markdown: {report / 'testplan_doc.md'}")
        show("The local viewer stays open while the orchestrator terminal is running.")
        show("On a remote host, forward the printed port to your browser before opening the URL.")

    def plan():
        derived = any(s["tool"] == "rtl_build_spec" for s in flow["steps"])
        if not scan or (not scan["specs"] and not derived) or not all(variables.get(k) for k in ("repo", "rtl_files", "rtl_graph_files", "rtl_top")):
            show("Name a local repository with RTL, a clear top module, and a specification or RTL-derived draft path first.")
            return False
        try:
            use_llm, use_embedder = models()
        except ValueError as exc:
            show(f"Plan blocked: {exc}")
            return False
        if use_llm is None and not derived:
            show("Plan blocked: MODEL_API_KEY is required for a specification-grounded testplan.")
            return False
        out.mkdir(parents=True, exist_ok=True)
        if use_llm is not None and getattr(use_llm,'timeout',None) is not None:
            show(f"Model requests: {use_llm.timeout:g}s timeout, up to {use_llm.max_attempts} attempts. "
                 f"Detailed log: {out / 'dv' / 'llm_requests.jsonl'}")
        ask = dict(requirement=requirement, flow=str(flow_path), out=str(out), variables=variables)
        (out / ASK_FILE).write_text(json.dumps(ask, indent=2), encoding="utf-8")
        dash = Dashboard(out, show, flow=flow, title=requirement, ansi=interactive) if use_dashboard else None
        result = run_flow(flow_path, out_dir=out, variables=dict(variables), llm=use_llm,
                          embedder=use_embedder, registry=registry,
                          event_sink=dash.handle if dash else None)
        show(f"Plan: {result['status']} — {result['reason']}")
        if derived and (out / "rtl_spec" / "doc" / "rtl_derived_spec.md").is_file():
            show(f"RTL-derived specification (INFERRED, engineer review required): {out / 'rtl_spec' / 'doc' / 'rtl_derived_spec.md'}")
            if use_llm is None:
                show("The inferred specification draft is ready. MODEL_API_KEY is required to continue to the testplan.")
        if (out / "dv" / "testplan_doc.json").is_file():
            show(f"Testplan: {out / 'dv' / 'testplan_doc.md'}")
            show(f"Readable copy: {out / 'dv' / 'testplan_doc.html'}")
            show_viewer()
        if result["status"] != "PASS":
            show(f"Review details: {out / REVIEW_FILE}")
        return result["status"] == "PASS"

    def fresh():
        nonlocal out, variables, requirement, scan, flow_path, flow, restore_saved
        previous = out
        out = fresh_out()
        variables = {"include": [], "scope": ""}
        requirement = ""
        scan = None
        restore_saved = False
        flow_path = _builtin_flow()
        flow = load_flow(flow_path)
        show(f"Fresh session in {out} — no cached state is reused. "
             f"Earlier run kept at {previous}.")

    def rerun(target: str) -> None:
        planned = rerun_plan(target, out, variables)
        if planned is None:
            show(rerun_help())
            return
        tool, args = planned
        if tool in ("dv_ingest", "rtl_extract", "rtl_build_graph") and not variables.get("repo"):
            show("Name a local repository first, then rerun.")
            return
        try:
            use_llm, use_embedder = models()
        except ValueError as exc:
            show(f"Rerun blocked: {exc}")
            return
        result = run_single_tool(tool, args, out_dir=out, llm=use_llm,
                                 embedder=use_embedder, registry=registry)
        show(f"Rerun {tool}: {result['status']} — {result.get('summary', '')}")

    def assist(ask: dict) -> None:
        intent = ask["intent"]
        if intent == "fresh":
            fresh()
        elif intent == "help":
            show(HELP)
        elif intent == "explain":
            for text in explain_run(out):
                show(text)
        elif intent == "status":
            target = Path(ask["path"]).expanduser() if ask["path"] else out
            for text in status_text(target):
                show(text)
        elif intent == "validate":
            if not ask["path"]:
                show("usage: validate <flow.json>")
                return
            for text in validate_text(ask["path"]):
                show(text)
        elif intent == "show":
            for text in show_text(out, ask["target"]):
                show(text)
        elif intent == "rerun":
            rerun(ask["target"])

    while True:
        try:
            line = read("orch> ").strip()
        except (EOFError, KeyboardInterrupt):
            if viewer is not None:
                viewer.shutdown()
                viewer.server_close()
                if viewer_thread is not None:
                    viewer_thread.join(timeout=2)
            show("")
            return 0
        if not line:
            continue
        if line == "/fresh":
            fresh()
            continue
        ask = interpret(line)
        if ask is not None:
            assist(ask)
            continue
        if not line.startswith("/") or (line not in ("/plan", "/code", "/run", "/regress", "/fresh") and Path(line).is_dir()):
            requirement = line
            repo = find_repo(line, PACKAGE_ROOT)
            if repo is not None:
                try:
                    scan = inspect_repo(repo, line)
                    flow_path = (_rtl_derived_flow() if not scan["specs"] or _asks_for_rtl_spec(line)
                                 else _builtin_flow())
                    flow = load_flow(flow_path)
                    variables = dict(include=[], scope="", repo=str(scan["repo"]),
                                     rtl_files=[str(scan["top_file"])] if scan["top_file"] else [],
                                     rtl_graph_files=[str(p) for p in scan["rtl_files"]],
                                     rtl_top=scan["top"])
                    if not matches_current_run(out, variables):
                        out = fresh_out()
                except (OSError, ValueError) as exc:
                    scan = None
                    show(f"Repository scan failed: {exc}")
            else:
                scan = None
                variables = {"include": [], "scope": ""}
            show(ask_card(flow, flow_path, variables, requirement, out, scan=scan))
            continue
        if line == "/plan":
            plan()
        elif line == "/code":
            if not (out / "dv" / "testplan_doc.json").is_file() and restore_saved:
                saved = latest_successful(PACKAGE_ROOT / 'runs', variables)
                if saved:
                    out, saved_ask = saved
                    variables = dict(saved_ask['variables'])
                    requirement = saved_ask.get('requirement', requirement)
                    show(f"Using saved successful testplan: {out / 'dv/testplan_doc.json'}")
            if not (out / "dv" / "testplan_doc.json").is_file():
                show("No saved testplan; generating it first.")
                plan()
            if not (out / "dv" / "testplan_doc.json").is_file():
                show("Code blocked: no testplan was generated.")
                continue
            try:
                from dv_agent.quality.quick_testing import enabled, prepare_run, WARNING
                if enabled():
                    out = prepare_run(out)
                    show(WARNING)
                    show(f'Isolated quick-testing output: {out}')
                for notice in code_notice(json.loads((out / "dv" / "testplan_doc.json").read_text(encoding="utf-8"))):
                    show(notice)
                if abort_requested(interactive=input_fn is None):
                    show("Code aborted before it started; nothing was generated.")
                    continue
                show(code_preview(out))
                code_llm, _ = models()
                result = execute_code(build_code, out, variables, llm=code_llm, show=show,
                                      dashboard=use_dashboard, ansi=interactive)
                if result.get('status')=='WAITING_HUMAN':
                    show(result['reason'])
                    continue
                policy = result["policy"]
                if result.get('contract'):
                    show(f"Code: {result['code_dir']} ({policy['kept']} cited documented facts used for behavior; "
                         "plan proposals guide implementation only).")
                else:
                    show(f"Code: {result['code_dir']} ({policy['kept']} documented items retained as code input; "
                         f"{policy['skipped']} unsupported or inferred items excluded).")
                show(f"Built tests: {', '.join(t['name'] for t in result['tests'])}.")
                if result.get('work_documents'):
                    show(f"Feature dependencies and pseudocode: {result['work_documents']}")
                if result.get("contract"):
                    show(f"Functional compile: {result['compile']['status']}; generated expectations require review.")
                    if result['compile'].get('reason'): show(result['compile']['reason'])
                else:
                    show("Legacy scaffold: compile/clock/reset smoke only; no functional behavior claimed.")
            except KeyboardInterrupt:
                show("Code interrupted; saved checkpoints are kept. Use /code to retry.")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                show(f"Code blocked: {exc}")
                if (out/'code_work_manifest.json').is_file():
                    show(f"Partial feature documents: {out/'code_work_manifest.json'}")
        elif line in ("/run", "/regress"):
            try:
                result = run_tests(out, regress=line == "/regress")
                for test in result["tests"]:
                    show(f"{test['name']}: {test['status']} — {test['reason']}"
                         + (f" ({test['log']})" if test.get("log") else ""))
                show(f"{line[1:]}: {result['status']}")
                if result.get('reason'): show(result['reason'])
                if result.get('compile',{}).get('reason'): show(result['compile']['reason'])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                show(f"{line[1:]} blocked: {exc}")
        else:
            show(HELP)
