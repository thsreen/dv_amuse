"""dv-agent CLI: ingest | build-graph | interfaces | registers | strategy | plan | testplan | pipeline | query |
context | deps | features | lineage | usage."""
import argparse
import json
import os
import sys
from pathlib import Path

from .dense import MetaEmbedder
from .graph import lineage, load_graph
from .llm import MetaClient
from .fsutil import atomic_write_text
from .pipeline import (GRAPH_FILE, clear_llm_cache, clear_run, run_build_graph, run_context, run_deps, run_features,
                       run_ingest, run_interfaces, run_query, run_registers, run_strategy, run_test_plan, run_usage,
                       run_testplan_doc)
from .planning import PlanConfig
from .progress import emit, set_sink, stderr_sink
from .usage import run_totals
from .retrieval import RetrievalConfig

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


def _require(out: Path, *names: str) -> None:
    missing = [n for n in names if not (out / n).exists()]
    if missing:
        raise UsageError(f"{out} is missing {', '.join(missing)}; run the earlier stage first "
                         "(ingest, then build-graph)")


def _save_and_print(obj, save: Path | None) -> None:
    if save is not None:
        atomic_write_text(save, json.dumps(obj, indent=2, default=str))
    _print(obj)


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

    pt = sub.add_parser("testplan", help="generate the template-driven test-plan document (JSON + Markdown)")
    pt.add_argument("--out", type=Path, required=True)
    pt.add_argument("--scope", default="", help="feature or block the plan covers (default: whole specification)")
    pt.add_argument("--template", type=Path, help="template JSON (default: built-in quick_reference_v0)")
    pt.add_argument("--force", action="store_true", help="regenerate even if the document is current")
    pt.add_argument("--fresh", action="store_true", help="delete the LLM cache and regenerate")
    pt.add_argument("--rtl-graph", type=Path, help="opt in to review-required implementation observations from this graph")
    pt.add_argument("--rtl-scope", default="", help="instance scope within --rtl-graph")

    pa = sub.add_parser("pipeline", help="ingest, build the graph and (optionally) plan in one command")
    pa.add_argument("repo", type=Path)
    pa.add_argument("--out", type=Path, help="run directory (default: runs/<repo name>)")
    pa.add_argument("--include", action="append")
    pa.add_argument("--requirements", nargs="*", default=[], help="requirement IDs to plan")
    pa.add_argument("--testplan", action="store_true", help="also generate the template-driven test-plan document")
    pa.add_argument("--scope", default="", help="test-plan scope (with --testplan)")
    pa.add_argument("--template", type=Path, help="test-plan template JSON (with --testplan)")
    pa.add_argument("--rtl-graph", type=Path, help="RTL observations graph (requires --testplan)")
    pa.add_argument("--rtl-scope", default="", help="instance scope within --rtl-graph")
    pa.add_argument("--force", action="store_true", help="rerun every stage regardless of existing outputs")
    pa.add_argument("--fresh", action="store_true",
                    help="delete all generated artifacts (cache, graph, plan, trace) and run from scratch")
    pa.add_argument("--llm", choices=LLM_MODES, help="auto (default), on, or off; env DV_AGENT_LLM_MODE")

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
    if args.cmd in ("ingest", "build-graph", "plan", "interfaces", "registers", "strategy",
                    "testplan", "pipeline"):
        set_sink(stderr_sink)  # progress goes to stderr; stdout stays pure JSON
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
        emit(f"building graph in {args.out} (--llm {_llm_mode(args.llm)})")
        result = run_build_graph(args.out, llm, embedder=embedder, force=force)
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
        result = step(args.out, llm, scope=args.scope, embedder=_embedder(), force=args.force or args.fresh)
        emit(f"{args.cmd} done: {result['status']}" + (" (reused cached output)" if result.get("reused") else ""))
        _print(result | {"cache_cleared": removed})
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
                                  rtl_graph_path=args.rtl_graph, rtl_scope=args.rtl_scope)
        if result.get("reused"):
            emit("testplan done: reused cached document")
        else:
            emit(f"testplan done: {len(result['sections'])} sections written")
        _print(result | {"cache_cleared": removed})
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
        emit(f"[1/{len(stages)}] ingest: {args.repo} -> {out}")
        result["ingest"] = run_ingest(args.repo, out, args.include, force=force)
        emit(f"ingest done: {result['ingest']['chunks']} chunks")
        if llm is not None:
            llm.cache_dir = out / "llm_cache"
        emit(f"[2/{len(stages)}] build-graph (--llm {_llm_mode(args.llm)})")
        result["build"] = run_build_graph(out, llm, embedder=embedder, force=force)
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
                                                  rtl_graph_path=args.rtl_graph, rtl_scope=args.rtl_scope)
        emit("pipeline done")
        ran = [r["trace_id"] for r in (result.get(k) for k in ("ingest", "build", "plan", "testplan"))
               if r and not r.get("reused") and r.get("trace_id")]
        result["usage"] = run_totals(out / "trace.jsonl", ran) if ran else None
        _print(result)
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
