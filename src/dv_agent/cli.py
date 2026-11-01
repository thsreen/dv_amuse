"""dv-agent CLI: ingest | build-graph | interfaces | registers | strategy | plan | testplan | pipeline | query |
context | deps | features | lineage | usage."""
import argparse
import json
import os
import sys
from pathlib import Path

from .retrieval.dense import MetaEmbedder
from .graph.graph import lineage, load_graph
from .core.llm import MetaClient
from .core.fsutil import atomic_write_text
from .pipeline import (GRAPH_FILE, clear_llm_cache, clear_run, run_build_graph, run_context, run_deps, run_features,
                       run_ingest, run_interfaces, run_query, run_registers, run_strategy, run_test_plan, run_usage,
                       run_testplan_doc, render_testplan)
from .plan.planning import PlanConfig
from .core.progress import emit, set_global_sink, stderr_sink
from .core.usage import run_totals
from .retrieval.retrieval import RetrievalConfig

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def load_env_file(path: Path) -> None:
    """Minimal .env loader; never overrides variables already set in the environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


LLM_MODES = ("auto", "on", "off")


def _llm() -> MetaClient | None:
    return MetaClient() if os.getenv("MODEL_API_KEY", "").strip() else None


def _embedder() -> MetaEmbedder | None:
    if not (os.getenv("MODEL_API_KEY", "").strip() and os.getenv("META_EMBED_MODEL", "").strip()):
        return None
    return MetaEmbedder()


def _llm_mode(arg: str | None) -> str:
    mode = (arg or os.getenv("DV_AGENT_LLM_MODE", "") or "auto").strip().lower()
    if mode not in LLM_MODES:
        raise UsageError(f"LLM mode must be one of {LLM_MODES}, got {mode!r}")
    return mode


def _mode(arg: str | None) -> str:
    mode = (arg or os.getenv("DV_AGENT_MODE", "") or "basic").strip().lower()
    if mode not in ("basic", "graph"):
        raise UsageError(f"mode must be one of ('basic', 'graph'), got {mode!r}")
    return mode


def _models_for(mode: str):
    """(llm, embedder) honouring the mode: off never calls the API; on requires a key."""
    if mode == "off":
        return None, None
    llm = _llm()
    if llm is None and mode == "on":
        raise UsageError("LLM mode is 'on' but MODEL_API_KEY is not set")
    return llm, _embedder() if llm is not None else None


class UsageError(Exception):
    pass


def _extract_config(workers: int | None):
    """ExtractConfig from --workers (None keeps the DV_AGENT_MAX_WORKERS default)."""
    if workers is None:
        return None
    from .ingest.extract import MAX_WORKERS_CAP, ExtractConfig
    if workers < 1:
        raise UsageError(f"--workers must be at least 1, got {workers}")
    return ExtractConfig(max_workers=min(workers, MAX_WORKERS_CAP))


def _require(out: Path, *names: str) -> None:
    missing = [n for n in names if not (out / n).exists()]
    if missing:
        raise UsageError(f"{out} is missing {', '.join(missing)}; run the earlier stage first "
                         "(ingest, then build-graph)")


def _save_and_print(obj, save: Path | None) -> None:
    if save is not None:
        atomic_write_text(save, json.dumps(obj, indent=2, default=str))
    _print(obj)


def _notify_plan(out: Path, result: dict) -> None:
    """Send the generated testplan HTML to Telegram when one is configured; a failure never affects the command."""
    if result.get("status") != "PASS":
        return
    from .core.notifications import notify_testplan
    sent = notify_testplan(out)
    result["testplan_notification"] = sent["status"]
    if sent["status"] != "SKIPPED":
        emit(f"testplan notification: {sent['status']}")


def _print(obj) -> None:
    json.dump(obj, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (UsageError, ValueError, KeyError) as exc:
        message = exc.args[0] if exc.args else type(exc).__name__
        print(f"error: {message}", file=sys.stderr)
        return 2


def _main(argv: list[str] | None) -> int:
    load_env_file(PACKAGE_ROOT / ".env")
    p = argparse.ArgumentParser(prog="dv-agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="discover and chunk spec documents in a design repository")
    pi.add_argument("repo", type=Path)
    pi.add_argument("--out", type=Path, help="run directory (default: runs/<repo name>)")
    pi.add_argument("--include", action="append", help="glob (repo-relative) to select documents")
    pi.add_argument("--force", action="store_true", help="re-ingest even if the run directory is current")

    pb = sub.add_parser("build-graph", help="build the 3-layer graph (LLM layers need MODEL_API_KEY)")
    pb.add_argument("--out", type=Path, required=True)
    pb.add_argument("--llm", choices=LLM_MODES, help="auto (default; LLM if a key is set), on (require), off "
                    "(structural layers only, no API calls); env DV_AGENT_LLM_MODE")
    pb.add_argument("--force", action="store_true", help="rebuild the graph even if it is current")
    pb.add_argument("--fresh", action="store_true", help="delete the LLM cache and rebuild from scratch")
    pb.add_argument("--workers", type=int, default=None, metavar="N",
                    help="parallel extraction calls, 1-4 (default 1; env DV_AGENT_MAX_WORKERS)")
    pb.add_argument("--mode", choices=("basic", "graph"),
                    help="basic (default; lexical RAG, slim index) or graph (model-built knowledge graph); env DV_AGENT_MODE")

    pp = sub.add_parser("plan", help="build verification test-plan items for requirements")
    pp.add_argument("requirement_ids", nargs="+")
    pp.add_argument("--out", type=Path, required=True)
    pp.add_argument("--force", action="store_true", help="regenerate the test plan even if it is current")
    pp.add_argument("--fresh", action="store_true", help="delete the LLM cache and regenerate")

    step_help = {"interfaces": "isolate interface definitions and group them by functionality and module type",
                 "registers": "fetch the register map definitions from the specification",
                 "strategy": "build the verification strategy from the interface and register steps"}
    for name, help_text in step_help.items():
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--out", type=Path, required=True)
        sp.add_argument("--scope", default="", help="block or feature to focus retrieval on (default: whole spec)")
        sp.add_argument("--force", action="store_true", help=f"regenerate even if {name}.json is current")
        sp.add_argument("--fresh", action="store_true", help="delete the LLM cache and regenerate")
        sp.add_argument("--mode", choices=("basic", "graph"),
                        help="basic (default; lexical RAG, slim index) or graph (model-built knowledge graph); env DV_AGENT_MODE")

    pt = sub.add_parser("testplan", help="generate the template-driven test-plan document (JSON + Markdown + HTML)")
    pt.add_argument("--out", type=Path, required=True)
    pt.add_argument("--scope", default="", help="feature or block the plan covers (default: whole specification)")
    pt.add_argument("--template", type=Path, help="template JSON (default: built-in quick_reference_v0)")
    pt.add_argument("--methodology-rules", type=Path,
                    help="methodology rules JSON extending the shipped defaults")
    pt.add_argument("--force", action="store_true", help="regenerate even if the document is current")
    pt.add_argument("--fresh", action="store_true", help="delete the LLM cache and regenerate")
    pt.add_argument("--rtl-graph", type=Path, help="opt in to review-required implementation observations from this graph")
    pt.add_argument("--rtl-scope", default="", help="instance scope within --rtl-graph")
    pt.add_argument("--mode", choices=("basic", "graph"),
                    help="basic (default; lexical RAG, slim index) or graph (model-built knowledge graph); env DV_AGENT_MODE")

    pr = sub.add_parser("render-testplan", help="refresh HTML from editable testplan Markdown without model calls")
    pr.add_argument("--out", type=Path, help="run or runs directory (default with --serve: runs/)")
    pr.add_argument("--serve", action="store_true", help="start a local viewer with a Render testplan button")
    pr.add_argument("--port", type=int, default=8765, help="local viewer port with --serve (default: 8765)")
    pf=sub.add_parser('review-feedback',help='Apply edited Markdown feedback; report-review completion only')
    pf.add_argument('--out',type=Path,required=True,help='directory containing testplan_doc.json (usually run/dv)')
    pf.add_argument('--file',type=Path,required=True,help='edited testplan Markdown')
    pf.add_argument('--reviewer',required=True,help='human reviewer name')

    pa = sub.add_parser("pipeline", help="ingest, build the graph and (optionally) plan in one command")
    pa.add_argument("repo", type=Path)
    pa.add_argument("--out", type=Path, help="run directory (default: runs/<repo name>)")
    pa.add_argument("--include", action="append")
    pa.add_argument("--requirements", nargs="*", default=[], help="requirement IDs to plan")
    pa.add_argument("--testplan", action="store_true", help="also generate the template-driven test-plan document")
    pa.add_argument("--scope", default="", help="test-plan scope (with --testplan)")
    pa.add_argument("--template", type=Path, help="test-plan template JSON (with --testplan)")
    pa.add_argument("--methodology-rules", type=Path,
                    help="methodology rules JSON extending the shipped defaults (with --testplan)")
    pa.add_argument("--rtl-graph", type=Path, help="RTL observations graph (requires --testplan)")
    pa.add_argument("--rtl-scope", default="", help="instance scope within --rtl-graph")
    pa.add_argument("--force", action="store_true", help="rerun every stage regardless of existing outputs")
    pa.add_argument("--fresh", action="store_true",
                    help="delete all generated artifacts (cache, graph, plan, trace) and run from scratch")
    pa.add_argument("--llm", choices=LLM_MODES, help="auto (default), on, or off; env DV_AGENT_LLM_MODE")
    pa.add_argument("--workers", type=int, default=None, metavar="N",
                    help="parallel extraction calls, 1-4 (default 1; env DV_AGENT_MAX_WORKERS)")
    pa.add_argument("--mode", choices=("basic", "graph"),
                    help="basic (default; lexical RAG, slim index) or graph (model-built knowledge graph); env DV_AGENT_MODE")

    pv = sub.add_parser("evaluate", help="recall@k and MRR of retrieval on a labelled question set (no LLM)")
    pv.add_argument("--out", type=Path, required=True, help="run directory with a built graph")
    pv.add_argument("--cases", type=Path, default=Path("eval/uart_cases.json"))
    pv.add_argument("--k", type=int, nargs="+", default=[1, 3, 5], help="cut-offs to report")
    pv.add_argument("--ablate", action="store_true",
                    help="also report lexical only (no graph propagation) beside the full configuration")
    pv.add_argument("--table", action="store_true", help="print a Markdown table instead of JSON")

    pq = sub.add_parser("query", help="retrieve ranked evidence with graph paths")
    pq.add_argument("text")
    pq.add_argument("--out", type=Path, required=True)
    pq.add_argument("--top-k", type=int, default=8)

    pc = sub.add_parser("context", help="cited evidence bundle for a test-plan topic or requirement (no LLM)")
    pc.add_argument("topic", nargs="?", help="feature or topic, e.g. 'receiver FIFO timeout interrupt'")
    pc.add_argument("--requirement", help="requirement ID instead of a topic")
    pc.add_argument("--out", type=Path, required=True)
    pc.add_argument("--top-k", type=int, default=8)
    pc.add_argument("--save", type=Path, help="also write the bundle JSON to this file")
    pc.add_argument("--global", dest="global_communities", type=int, default=None, metavar="N",
                    help="number of best-matching communities to expand (default 2; 0 disables)")

    pd = sub.add_parser("deps", help="dependency closure and precondition-first order for requirements")
    pd.add_argument("requirement_ids", nargs="+")
    pd.add_argument("--out", type=Path, required=True)
    pd.add_argument("--depth", type=int, default=4)

    pf = sub.add_parser("features", help="specification outline (sections, communities, requirements)")
    pf.add_argument("--out", type=Path, required=True)
    pf.add_argument("--save", type=Path, help="also write the outline JSON to this file")

    pu = sub.add_parser("usage", help="tokens (input, cached input, output, reasoning) per run and per model call")
    pu.add_argument("--out", type=Path, required=True)
    pu.add_argument("--trace", help="only this run (trace ID)")
    pu.add_argument("--last", type=int, help="only the last N runs")

    pl = sub.add_parser("lineage", help="facts and source chunks behind a graph node")
    pl.add_argument("node_id")
    pl.add_argument("--out", type=Path, required=True)

    # Existing entry point forwards to the independent RTL package.
    from rtl_agent.cli import add_commands
    add_commands(sub)

    pcode = sub.add_parser("build-code", help="build functional verification from a documented testplan and code contract")
    pcode.add_argument("--testplan", type=Path, required=True)
    pcode.add_argument("--interface", type=Path, required=True)
    pcode.add_argument("--out", type=Path, required=True)
    pcode.add_argument("--contract", type=Path, help="explicit code_plan.json; otherwise model designs one")
    pcode.add_argument("--rtl-file", type=Path, action="append", required=True)
    pcode.add_argument("--top", required=True)
    pcode.add_argument("--llm", choices=LLM_MODES, default="auto")
    pcode.add_argument("--compile", action="store_true", help="explicit standalone compile; generation normally defers simulation")
    pcode.add_argument("--no-compile", action="store_true", help="record compilation as NOT_RUN")

    prun = sub.add_parser('run-code', help='compile and simulate saved functional verification code; no model calls')
    prun.add_argument('--out',type=Path,required=True,help='run directory containing code_manifest.json')
    prun.add_argument('--regress',action='store_true',help='run all built tests instead of the first test')
    prun.add_argument('--timeout',type=int,default=180,help='wall-clock deadline per compilation/test, seconds (default 180)')

    pwork = sub.add_parser('plan-code',help='write feature dependencies and pseudocode from a saved testplan; no SV generation')
    pwork.add_argument('--out',type=Path,required=True,help='saved run containing dv/testplan_doc.json and rtl/interface_definition.json')
    pwork.add_argument('--llm',choices=LLM_MODES,default='auto')

    puvm = sub.add_parser("build-uvm", help="build an extendable UVM scaffold from interface JSON")
    puvm.add_argument("interface", type=Path, help="interface_definition.json")
    puvm.add_argument("--out", type=Path, required=True, help="separate coding-flow output directory")
    puvm.add_argument("--prefix", help="generated SV class prefix (or name in --agent-args)")
    puvm.add_argument("--clock", required=True, help="explicit scalar DUT input clock")
    puvm.add_argument("--reset", help="explicit scalar DUT input reset for the common reset UVC")
    puvm.add_argument("--reset-active", choices=("high", "low"),
                      help="required with --reset; no polarity is inferred from the name")
    puvm.add_argument("--testplan", type=Path, help="testplan_doc.json for named sequence skeletons")
    puvm.add_argument("--agent-args", type=Path,
                      help="template_id/name/custom code arguments for the UVM agent template")
    puvm.add_argument("--llm", choices=("off", "on"), default="off",
                      help="opt-in plan-to-control extraction; requires --testplan and MODEL_API_KEY")
    puvm.add_argument("--force", action="store_true", help="replace generated files in the output directory")

    args = p.parse_args(argv)
    if args.cmd=='plan-code':
        from .codegen.build import load_sources,project_lock
        from .codegen.workplan import design as plan_work
        from .quality.human_review import HumanReviewPending,PlanUpdated,ReviewClient,review_handler,plan_location
        from .core.llm import LLMError
        llm,_=_models_for(args.llm)
        if llm is None: raise UsageError('plan-code requires an enabled model')
        set_global_sink(stderr_sink)
        try:
            plan=json.loads((args.out/'dv/testplan_doc.json').read_text())
            definition=json.loads((args.out/'rtl/interface_definition.json').read_text())
            with project_lock(args.out), plan_location(args.out/'dv/testplan_doc.json'), review_handler(ReviewClient(llm=llm)):
                from .codegen.port_comparison import enforce
                for clarification in range(8):
                    plan=json.loads((args.out/'dv/testplan_doc.json').read_text())
                    try:
                        enforce(plan,definition,args.out)
                        result=plan_work(llm,plan,definition,load_sources(plan,args.out/'dv/graph.json'),args.out,pseudocode_only=True)
                        break
                    except PlanUpdated: continue
                else: raise HumanReviewPending('Clarification revision limit reached; resume plan-code')
        except HumanReviewPending as exc:
            _print(dict(status='WAITING_HUMAN',reason=str(exc),out=str(args.out)))
            return 0
        except LLMError as exc:
            raise UsageError('Code planning model call failed: '+exc.kind+'; rerun to reuse completed responses') from None
        except OSError as exc:
            raise UsageError(f'Code planning input unavailable: {exc}') from None
        _print(result)
        return 0
    if args.cmd == 'run-code':
        from .codegen.simulator import run_saved_project
        if args.timeout<=0: raise UsageError('--timeout must be positive')
        try:
            result=run_saved_project(args.out,regress=args.regress,timeout=args.timeout)
        except OSError as exc:
            raise UsageError(f'Simulation input/tool unavailable: {exc}') from None
        _print(result)
        return 0 if result['status']=='PASS' else 1
    if args.cmd == "build-code":
        from .codegen import build_project
        from .quality.human_review import HumanReviewPending,ReviewClient,review_handler
        set_global_sink(stderr_sink)
        llm, _ = _models_for(args.llm)
        try:
            with review_handler(ReviewClient(llm=llm)):
                result = build_project(args.testplan,args.interface,args.out,llm=llm,contract_path=args.contract,
                                       rtl_files=args.rtl_file,expected_top=args.top,compile=args.compile and not args.no_compile)
        except HumanReviewPending as exc:
            _print(dict(status='WAITING_HUMAN',reason=str(exc),out=str(args.out)))
            return 0
        except OSError as exc:
            raise UsageError(f"Code generation input/tool unavailable: {exc}") from None
        print(json.dumps(result,indent=2))
        return 0 if result['compile']['status'] in ('PASS','NOT_RUN') else 1
    if args.cmd in ("ingest", "build-graph", "plan", "interfaces", "registers", "strategy",
                    "testplan", "pipeline"):
        set_global_sink(stderr_sink)  # progress goes to stderr, incl. worker threads
    if args.cmd == "build-uvm":
        from .uvm import build_uvm, write_uvm
        if not args.interface.is_file():
            raise UsageError(f"interface file not found: {args.interface}")
        if args.testplan and not args.testplan.is_file():
            raise UsageError(f"test plan file not found: {args.testplan}")
        if args.agent_args and not args.agent_args.is_file():
            raise UsageError(f"agent arguments file not found: {args.agent_args}")
        if args.llm == "on" and not args.testplan:
            raise UsageError("--llm on requires --testplan")
        llm = _llm() if args.llm == "on" else None
        if args.llm == "on" and llm is None:
            raise UsageError("MODEL_API_KEY is required for --llm on")
        try:
            definition = json.loads(args.interface.read_text(encoding="utf-8"))
            plan = json.loads(args.testplan.read_text(encoding="utf-8")) if args.testplan else None
            agent_args = json.loads(args.agent_args.read_text(encoding="utf-8")) if args.agent_args else None
        except json.JSONDecodeError as exc:
            raise UsageError(f"input JSON is invalid: {exc}") from None
        artifacts, manifest = build_uvm(definition, prefix=args.prefix, clock=args.clock,
                                        reset=args.reset, reset_active=args.reset_active,
                                        plan=plan, llm=llm, agent_args=agent_args)
        write_uvm(args.out, artifacts, inputs=[p for p in (args.interface, args.testplan, args.agent_args) if p],
                  force=args.force)
        _print({"out": str(args.out), "files": sorted(artifacts), "status": manifest["status"]})
    elif args.cmd in ("rtl-interfaces", "build-interface"):
        from rtl_agent.commands import run_rtl_command
        _print(run_rtl_command(args))
    elif args.cmd == "ingest":
        out = args.out or PACKAGE_ROOT / "runs" / args.repo.resolve().name
        emit(f"ingesting {args.repo} into {out}")
        result = run_ingest(args.repo, out, args.include, force=args.force)
        emit(f"ingest done: {result['chunks']} chunks" + (" (reused cached output)" if result.get("reused") else ""))
        _print(result | {"out": str(out)})
    elif args.cmd == "build-graph":
        _require(args.out, "manifest.json", "chunks.jsonl")
        llm, embedder = _models_for(_llm_mode(args.llm))
        removed = clear_llm_cache(args.out) if args.fresh else False
        force = args.force or args.fresh
        if llm is not None:
            llm.cache_dir = args.out / "llm_cache"
        emit(f"building graph in {args.out} (--llm {_llm_mode(args.llm)}, --mode {_mode(args.mode)})")
        result = run_build_graph(args.out, llm, _extract_config(args.workers),
                                      embedder=embedder, force=force, mode=_mode(args.mode))
        if result.get("reused"):
            emit("build done: reused cached graph")
        else:
            nodes = sum(result.get("nodes", {}).values())
            emit(f"build done: {nodes} nodes, {result.get('edges', 0)} edges, llm={result['llm']['status']}")
        _print(result | {"cache_cleared": removed})
    elif args.cmd == "plan":
        _require(args.out, GRAPH_FILE)
        llm = _llm()
        if llm is None:
            raise UsageError("MODEL_API_KEY is required for test-plan generation")
        removed = clear_llm_cache(args.out) if args.fresh else False
        llm.cache_dir = args.out / "llm_cache"
        emit(f"planning {len(args.requirement_ids)} requirements")
        result = run_test_plan(args.out, args.requirement_ids, llm, PlanConfig(retrieval=RetrievalConfig()),
                               embedder=_embedder(), force=args.force or args.fresh)
        emit(f"plan done: {len(result['items'])} items" + (" (reused cached output)" if result.get("reused") else ""))
        _print(result | {"cache_cleared": removed})
    elif args.cmd in ("interfaces", "registers", "strategy"):
        _require(args.out, GRAPH_FILE)
        llm = _llm()
        if llm is None:
            raise UsageError(f"MODEL_API_KEY is required for the {args.cmd} step")
        removed = clear_llm_cache(args.out) if args.fresh else False
        llm.cache_dir = args.out / "llm_cache"
        step = {"interfaces": run_interfaces, "registers": run_registers, "strategy": run_strategy}[args.cmd]
        emit(f"running the {args.cmd} step")
        result = step(args.out, llm, scope=args.scope, embedder=_embedder(), force=args.force or args.fresh,
                        mode=_mode(args.mode))
        emit(f"{args.cmd} done: {result['status']}" + (" (reused cached output)" if result.get("reused") else ""))
        _print(result | {"cache_cleared": removed})
    elif args.cmd == 'review-feedback':
        from .plan.human_feedback import apply
        _print(apply(args.out,args.file,args.reviewer))
    elif args.cmd == "render-testplan":
        if args.serve:
            from .report.testplan_viewer import create_report_server
            viewer_out = args.out or PACKAGE_ROOT / "runs"
            with create_report_server(viewer_out, args.port) as server:
                _print({"url": f"http://127.0.0.1:{server.server_port}/", "out": str(viewer_out.resolve()),
                        "message": "Open the URL, select a testplan, and click Render testplan after saving Markdown edits. Ctrl+C stops the viewer."})
                sys.stdout.flush()
                try:
                    server.serve_forever(poll_interval=0.25)
                except KeyboardInterrupt:
                    pass
        else:
            if args.out is None:
                raise UsageError("--out is required to render a single testplan without --serve")
            _print(render_testplan(args.out))
    elif args.cmd == "testplan":
        _require(args.out, GRAPH_FILE)
        llm = _llm()
        if llm is None:
            raise UsageError("MODEL_API_KEY is required for test-plan generation")
        removed = clear_llm_cache(args.out) if args.fresh else False
        llm.cache_dir = args.out / "llm_cache"
        emit("generating the test-plan document")
        result = run_testplan_doc(args.out, llm, scope=args.scope, template_path=args.template,
                                  embedder=_embedder(), force=args.force or args.fresh,
                                  rtl_graph_path=args.rtl_graph, rtl_scope=args.rtl_scope,
                                  mode=_mode(args.mode),
                                  methodology_rules_path=args.methodology_rules)
        _notify_plan(args.out, result)
        if result.get("reused"):
            emit("testplan done: reused cached document")
        else:
            emit(f"testplan {result['status']}: {len(result['sections'])} sections written")
        _print(result | {"cache_cleared": removed})
        if result.get("status") == "BLOCKED":
            return 1
    elif args.cmd == "pipeline":
        out = args.out or PACKAGE_ROOT / "runs" / args.repo.resolve().name
        llm, embedder = _models_for(_llm_mode(args.llm))
        if (args.rtl_graph or args.rtl_scope) and not args.testplan:
            raise UsageError("--rtl-graph/--rtl-scope require --testplan")
        if (args.requirements or args.testplan) and llm is None:
            raise UsageError("test-plan generation needs the LLM (MODEL_API_KEY set and --llm not off)")
        result = {"out": str(out)}
        force = args.force or args.fresh
        stages = ["ingest", "build"] + (["plan"] if args.requirements else []) + (["testplan"] if args.testplan else [])
        if args.fresh:
            result["cleared"] = clear_run(out)
            emit(f"cleared {len(result['cleared'])} cached artifacts (--fresh)")
        from .core.notifications import notify_start
        result['notification']=notify_start(out,'pipeline')
        emit('startup notification: '+result['notification']['status'])
        emit(f"[1/{len(stages)}] ingest: {args.repo} -> {out}")
        result["ingest"] = run_ingest(args.repo, out, args.include, force=force)
        emit(f"ingest done: {result['ingest']['chunks']} chunks")
        if llm is not None:
            llm.cache_dir = out / "llm_cache"
        emit(f"[2/{len(stages)}] build-graph (--llm {_llm_mode(args.llm)}, --mode {_mode(args.mode)})")
        result["build"] = run_build_graph(out, llm, _extract_config(args.workers),
                                                 embedder=embedder, force=force, mode=_mode(args.mode))
        pos = 2
        if args.requirements:
            pos += 1
            emit(f"[{pos}/{len(stages)}] plan: {len(args.requirements)} requirements")
            result["plan"] = run_test_plan(out, args.requirements, llm,
                                           PlanConfig(retrieval=RetrievalConfig()),
                                           embedder=embedder, force=force)
        if args.testplan:
            pos += 1
            emit(f"[{pos}/{len(stages)}] testplan: generating the test-plan document")
            result["testplan"] = run_testplan_doc(out, llm, scope=args.scope, template_path=args.template,
                                                  embedder=embedder, force=force,
                                                  rtl_graph_path=args.rtl_graph, rtl_scope=args.rtl_scope,
                                                  mode=_mode(args.mode),
                                                  methodology_rules_path=args.methodology_rules)
        if args.testplan:
            _notify_plan(out, result["testplan"])
            result["status"] = result["testplan"]["status"]
            emit(f"pipeline {result['status']}")
        else:
            emit("pipeline done")
        ran = [r["trace_id"] for r in (result.get(k) for k in ("ingest", "build", "plan", "testplan"))
               if r and not r.get("reused") and r.get("trace_id")]
        result["usage"] = run_totals(out / "trace.jsonl", ran) if ran else None
        _print(result)
        if result.get("status") == "BLOCKED":
            return 1
    elif args.cmd == "evaluate":
        from dataclasses import replace

        from .retrieval.evaluate import compare, format_table, load_cases
        _require(args.out, GRAPH_FILE)
        if not args.cases.is_file():
            raise UsageError(f"labelled cases not found: {args.cases}")
        if any(k < 1 for k in args.k):
            raise UsageError("--k values must be positive")
        base = RetrievalConfig()
        variants = {"graph retrieval (BM25 + PageRank)": base}
        if args.ablate:
            variants = {"lexical only (BM25)": replace(base, ppr_weight=0.0), **variants}
        result = compare(load_graph(args.out / GRAPH_FILE), load_cases(args.cases), sorted(set(args.k)), variants)
        print(format_table(result)) if args.table else _print(result)
    elif args.cmd == "query":
        _require(args.out, GRAPH_FILE)
        result = run_query(args.out, args.text, RetrievalConfig(top_k=args.top_k), embedder=_embedder())
        for e in result["evidence"]:
            e["text"] = e["text"][:300]
        _print(result)
    elif args.cmd == "context":
        _require(args.out, GRAPH_FILE)
        if (args.topic is None) == (args.requirement is None):
            raise UsageError("give a topic or --requirement, not both")
        bundle = run_context(args.out, topic=args.topic, requirement=args.requirement,
                             cfg=RetrievalConfig(top_k=args.top_k), embedder=_embedder(),
                             global_communities=args.global_communities)
        _save_and_print(bundle, args.save)
    elif args.cmd == "deps":
        _require(args.out, GRAPH_FILE)
        _print(run_deps(args.out, args.requirement_ids, args.depth))
    elif args.cmd == "features":
        _require(args.out, GRAPH_FILE)
        _save_and_print(run_features(args.out), args.save)
    elif args.cmd == "usage":
        _require(args.out, "trace.jsonl")
        _print(run_usage(args.out, args.trace, args.last))
    elif args.cmd == "lineage":
        _require(args.out, GRAPH_FILE)
        G = load_graph(args.out / GRAPH_FILE)
        if args.node_id not in G:
            raise UsageError(f"unknown node: {args.node_id}")
        _print(lineage(G, args.node_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
