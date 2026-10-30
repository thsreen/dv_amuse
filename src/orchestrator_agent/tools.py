"""Tool registry: one named entry per DV-agent or RTL-agent operation.

Each wrapper resolves its already-substituted arguments, calls the real
in-process API, and returns a small summary. Heavy payloads stay in the
artifacts on disk; only file paths and counts enter the orchestrator trace.
"""
import json
import os
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dv_agent import pipeline as dv_pipeline
from dv_agent.retrieval import RetrievalConfig
from rtl_agent import commands as rtl_commands
from rtl_agent import graph_commands as rtl_graph_commands

# Provenance tags. INTERFACE (port inventories) may feed UVM generation;
# RTL_BEHAVIOR (graph facts, excerpts, query bundles) may not.
SPEC = "SPEC"
INTERFACE = "INTERFACE"
RTL_BEHAVIOR = "RTL_BEHAVIOR"
UVM = "UVM"


@dataclass
class StepContext:
    out_dir: Path
    llm: Any = None
    embedder: Any = None
    extra_prompt: str = ""
    force: bool = False


@dataclass
class ToolSpec:
    agent: str
    tag: str
    needs_llm: bool
    run: Callable[[dict, StepContext], dict]


def _files(out: Path, *names: str) -> list[str]:
    return [str((out / n).resolve()) for n in names]


def _failed(tool: str, exc: Exception) -> dict:
    return dict(status="FAIL", summary=f"{tool} raised {type(exc).__name__}: {exc}",
                files=[], error=f"{type(exc).__name__}: {exc}")


def _opt_str(args: dict, key: str) -> str:
    value = args.get(key, "")
    return value if isinstance(value, str) else str(value)


def _dv_out(args: dict, ctx: StepContext) -> Path:
    return Path(args.get("out") or ctx.out_dir / "dv")


def _pipeline_mode(args: dict) -> str:
    return str(args.get("mode") or os.getenv("DV_AGENT_MODE") or "full").strip().lower()


def run_dv_ingest(args: dict, ctx: StepContext) -> dict:
    try:
        out = _dv_out(args, ctx)
        include = args.get("include") or None
        if isinstance(include, str):
            include = [include]
        res = dv_pipeline.run_ingest(Path(args["repo"]), out, include,
                                     force=args.get("force", ctx.force))
    except Exception as exc:
        return _failed("dv_ingest", exc)
    return dict(status="PASS", summary=f"ingested {res.get('chunks', 0)} chunks",
                files=_files(out, "manifest.json", "chunks.jsonl"), detail=res)


def run_dv_build_graph(args: dict, ctx: StepContext) -> dict:
    try:
        out = _dv_out(args, ctx)
        res = dv_pipeline.run_build_graph(out, ctx.llm, embedder=ctx.embedder,
                                          force=args.get("force", ctx.force), mode=_pipeline_mode(args))
    except Exception as exc:
        return _failed("dv_build_graph", exc)
    if res.get("llm", {}).get("status") == "BLOCKED":
        return dict(status="BLOCKED", summary=f"graph build blocked: {res['llm']}",
                    files=_files(out, "graph.json"), detail=res)
    return dict(status="PASS", summary=f"graph: {res.get('nodes', {})}",
                files=_files(out, "graph.json"), detail=res)


def _dv_step(name: str, runner, args: dict, ctx: StepContext, *files: str) -> dict:
    try:
        out = _dv_out(args, ctx)
        res = runner(out, ctx.llm, scope=_opt_str(args, "scope"),
                     embedder=ctx.embedder, force=args.get("force", ctx.force), mode=_pipeline_mode(args))
    except Exception as exc:
        return _failed(name, exc)
    if res.get("status") == "BLOCKED":
        return dict(status="BLOCKED", summary=f"{name} blocked: {res}", files=[], detail=res)
    return dict(status="PASS", summary=f"{name}: {res.get('status', 'PASS')}",
                files=_files(out, *files), detail=res)


def run_dv_interfaces(args: dict, ctx: StepContext) -> dict:
    return _dv_step("dv_interfaces", dv_pipeline.run_interfaces, args, ctx,
                    "interfaces.json", "interfaces.md")


def run_dv_registers(args: dict, ctx: StepContext) -> dict:
    return _dv_step("dv_registers", dv_pipeline.run_registers, args, ctx,
                    "registers.json", "registers.md")


def run_dv_strategy(args: dict, ctx: StepContext) -> dict:
    return _dv_step("dv_strategy", dv_pipeline.run_strategy, args, ctx,
                    "strategy.json", "strategy.md")


def run_dv_testplan(args: dict, ctx: StepContext) -> dict:
    try:
        out = _dv_out(args, ctx)
        template = _opt_str(args, "template")
        rtl_graph = _opt_str(args, "rtl_graph")
        res = dv_pipeline.run_testplan_doc(
            out, ctx.llm, scope=_opt_str(args, "scope"),
            template_path=Path(template) if template else None,
            embedder=ctx.embedder, force=args.get("force", ctx.force),
            rtl_graph_path=Path(rtl_graph) if rtl_graph else None,
            rtl_scope=_opt_str(args, "rtl_scope"), mode=_pipeline_mode(args))
    except Exception as exc:
        return _failed("dv_testplan", exc)
    sections = ", ".join(f"{s['id']}:{s['status']}" for s in res.get("sections", []))
    incomplete = [f"{s['id']}:{s['status']}" for s in res.get("sections", []) if s["status"] != "PASS"
                  and not (s["id"] == "rtl_observations" and not rtl_graph and s["status"] == "NOT_RUN")]
    for name in ("interfaces", "registers"):
        item = res.get(name)
        if item and item.get("status") not in ("PASS", "NOT_RUN"):
            incomplete.append(f"{name}:{item['status']}")
    return dict(status="BLOCKED" if incomplete else "PASS",
                summary=f"testplan [{sections}]" + (f"; incomplete: {', '.join(incomplete)}" if incomplete else ""),
                files=_files(out, "testplan_doc.json", "testplan_doc.md", "testplan_doc.html"),
                detail=dict(res, rtl_used=bool(rtl_graph)))


def run_dv_context(args: dict, ctx: StepContext) -> dict:
    try:
        out = _dv_out(args, ctx)
        topic = _opt_str(args, "topic") or None
        if topic and ctx.extra_prompt:
            topic = f"{topic}\nFollow-up: {ctx.extra_prompt}"
        res = dv_pipeline.run_context(
            out, topic=topic, requirement=args.get("requirement"),
            cfg=RetrievalConfig(top_k=int(args.get("top_k", 8))),
            embedder=ctx.embedder)
        files: list[str] = []
        if args.get("save"):
            save = Path(str(args["save"]))
            save.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
            files.append(str(save.resolve()))
    except Exception as exc:
        return _failed("dv_context", exc)
    return dict(status="PASS",
                summary=f"context: {len(res.get('chunks', []))} chunks, "
                        f"{len(res.get('requirements', []))} requirements",
                files=files, detail={"topic": topic})


def _rtl_namespace(cmd: str, args: dict, ctx: StepContext, **extra) -> Namespace:
    base = dict(cmd=cmd, out=Path(args.get("out") or ctx.out_dir / "rtl"))
    base.update(extra)
    return Namespace(**base)


def _str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def run_rtl_extract(args: dict, ctx: StepContext) -> dict:
    try:
        out = Path(args.get("out") or ctx.out_dir / "rtl")
        groups = _opt_str(args, "groups")
        ns = _rtl_namespace("rtl-interfaces", args, ctx,
                           files=[Path(p) for p in _str_list(args.get("files"))],
                           top=args.get("top", ""),
                           include_dir=[Path(p) for p in _str_list(args.get("include_dir"))],
                           define=_str_list(args.get("define")),
                           parameter=_str_list(args.get("parameter")),
                           build=bool(args.get("build", True)),
                           emit_sv=bool(args.get("emit_sv", False)),
                           name=args.get("name"), groups=Path(groups) if groups else None,
                           clock=args.get("clock"), edge=args.get("edge", "posedge"))
        res = rtl_commands.run_rtl_command(ns)
    except Exception as exc:
        return _failed("rtl_extract", exc)
    names = ["rtl_interfaces.json"] + (["interface_definition.json"] if ns.build else [])
    return dict(status="PASS", summary=f"extracted {res.get('ports', 0)} ports",
                files=_files(out, *names), detail=res)


def run_rtl_build_interface(args: dict, ctx: StepContext) -> dict:
    try:
        out = Path(args.get("out") or ctx.out_dir / "rtl")
        groups = _opt_str(args, "groups")
        ns = _rtl_namespace("build-interface", args, ctx,
                           contract=Path(args["contract"]),
                           name=args.get("name"), groups=Path(groups) if groups else None,
                           clock=args.get("clock"), emit_sv=bool(args.get("emit_sv", False)),
                           edge=args.get("edge", "posedge"))
        res = rtl_commands.run_rtl_command(ns)
    except Exception as exc:
        return _failed("rtl_build_interface", exc)
    return dict(status="PASS", summary=f"interface built ({res.get('ports', 0)} ports)",
                files=_files(out, "interface_definition.json"), detail=res)


def run_rtl_build_graph(args: dict, ctx: StepContext) -> dict:
    try:
        out = Path(args.get("out") or ctx.out_dir / "rtl_graph")
        features = _opt_str(args, "features")
        ns = _rtl_namespace("build-graph", args, ctx,
                           files=[Path(p) for p in _str_list(args.get("files"))],
                           top=args.get("top", ""),
                           include_dir=[Path(p) for p in _str_list(args.get("include_dir"))],
                           define=_str_list(args.get("define")),
                           parameter=_str_list(args.get("parameter")),
                           features=Path(features) if features else None,
                           max_instances=int(args.get("max_instances", 256)))
        res = rtl_graph_commands.run_graph_command(ns)
    except Exception as exc:
        return _failed("rtl_build_graph", exc)
    return dict(status="PASS",
                summary=f"rtl graph {res.get('analysis_status')}: "
                        f"{res.get('statistics', {})}",
                files=_files(out, "rtl_graph.json"), detail=res)


def run_rtl_build_spec(args: dict, ctx: StepContext) -> dict:
    try:
        from dv_agent.trace import Tracer
        from rtl_agent.specification import build_specification
        out = Path(args.get("out") or ctx.out_dir / "rtl_spec")
        template = _opt_str(args, "template")
        with Tracer(out / "trace.jsonl", "rtl_build_spec",
                    input={"graph": str(args["graph"])},
                    metadata={"model": getattr(ctx.llm, "model", None)}) as tracer:
            res = build_specification(Path(args["graph"]), out,
                                      Path(template) if template else None,
                                      llm=ctx.llm, tracer=tracer)
    except Exception as exc:
        return _failed("rtl_build_spec", exc)
    return dict(status="PASS", summary=f"RTL-derived draft: {res['claims']} inferred claims; RTL engineer review required",
                files=_files(out, "rtl_derived_spec.json", "doc/rtl_derived_spec.md"), detail=res)


def run_rtl_query(args: dict, ctx: StepContext) -> dict:
    try:
        text = _opt_str(args, "text")
        if ctx.extra_prompt:
            text = f"{text}\nFollow-up: {ctx.extra_prompt}"
        save = _opt_str(args, "save")
        ns = _rtl_namespace("query", args, ctx, text=text,
                           graph=Path(args["graph"]), scope=_opt_str(args, "scope"),
                           top_k=int(args.get("top_k", 16)),
                           hops=int(args.get("hops", 3)),
                           max_expansions=int(args.get("max_expansions", 256)),
                           save=Path(save) if save else None,
                           dense_index=None, query_vector=None)
        res = rtl_graph_commands.run_graph_command(ns)
    except Exception as exc:
        return _failed("rtl_query", exc)
    files = [str(Path(save).resolve())] if save else []
    return dict(status="PASS",
                summary=f"rtl context: {len(res.get('nodes', []))} nodes, "
                        f"{len(res.get('evidence', []))} excerpts",
                files=files, detail={"scope": ns.scope})


def run_uvm_build(args: dict, ctx: StepContext) -> dict:
    from dv_agent import uvm as uvm_mod
    try:
        interface = Path(args["interface"])
        if not interface.is_file():
            return dict(status="BLOCKED",
                        summary=f"interface file not found: {interface}",
                        files=[], error="missing interface JSON")
        out = Path(args.get("out") or ctx.out_dir / "uvm")
        notes: list[str] = []
        plan = None
        if _opt_str(args, "testplan"):
            plan_path = Path(args["testplan"])
            if plan_path.is_file():
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
            else:
                notes.append(f"testplan {plan_path} not found; building without plan names")
        agent_args = None
        if _opt_str(args, "agent_args"):
            agent_path = Path(args["agent_args"])
            if agent_path.is_file():
                agent_args = json.loads(agent_path.read_text(encoding="utf-8"))
            else:
                notes.append(f"agent_args {agent_path} not found; using generic template")
        llm_mode = args.get("llm", "off")
        llm = None
        if llm_mode == "on":
            if ctx.llm is None:
                return dict(status="BLOCKED",
                            summary="uvm_build llm=on needs MODEL_API_KEY",
                            files=[], error="no LLM configured")
            if plan is None:
                return dict(status="BLOCKED",
                            summary="uvm_build llm=on needs a testplan file",
                            files=[], error="llm=on without testplan")
            llm = ctx.llm
        definition = json.loads(interface.read_text(encoding="utf-8"))
        artifacts, manifest = uvm_mod.build_uvm(
            definition, prefix=args.get("prefix"), clock=args.get("clock", ""),
            reset=args.get("reset"), reset_active=args.get("reset_active"),
            plan=plan, llm=llm, agent_args=agent_args)
        inputs = [p for p in (interface, Path(args["testplan"]) if plan is not None else None,
                              Path(args["agent_args"]) if agent_args is not None else None)
                  if p is not None]
        uvm_mod.write_uvm(out, artifacts, inputs=inputs,
                          force=args.get("force", ctx.force))
    except Exception as exc:
        return _failed("uvm_build", exc)
    summary = f"uvm: {len(artifacts)} files, manifest {manifest.get('status')}"
    if notes:
        summary += f" ({'; '.join(notes)})"
    return dict(status="PASS", summary=summary,
                files=[str((out / n).resolve()) for n in artifacts],
                detail=dict(manifest_status=manifest.get("status"), notes=notes))


REGISTRY: dict[str, ToolSpec] = {
    "dv_ingest": ToolSpec("dv", SPEC, False, run_dv_ingest),
    "dv_build_graph": ToolSpec("dv", SPEC, False, run_dv_build_graph),
    "dv_interfaces": ToolSpec("dv", SPEC, True, run_dv_interfaces),
    "dv_registers": ToolSpec("dv", SPEC, True, run_dv_registers),
    "dv_strategy": ToolSpec("dv", SPEC, True, run_dv_strategy),
    "dv_testplan": ToolSpec("dv", SPEC, True, run_dv_testplan),
    "dv_context": ToolSpec("dv", SPEC, False, run_dv_context),
    "rtl_extract": ToolSpec("rtl", INTERFACE, False, run_rtl_extract),
    "rtl_build_interface": ToolSpec("rtl", INTERFACE, False, run_rtl_build_interface),
    "rtl_build_graph": ToolSpec("rtl", RTL_BEHAVIOR, False, run_rtl_build_graph),
    "rtl_build_spec": ToolSpec("rtl", RTL_BEHAVIOR, False, run_rtl_build_spec),
    "rtl_query": ToolSpec("rtl", RTL_BEHAVIOR, False, run_rtl_query),
    "uvm_build": ToolSpec("dv", UVM, False, run_uvm_build),
}
