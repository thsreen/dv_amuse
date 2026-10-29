"""Pipeline stages, each wrapped in its own trace."""
import json
import shutil
from pathlib import Path

from .community import build_communities
from .graph_fetch import add_owner_edges, dependency_closure, dependency_order
from .dense import Embedder, build_index, dense_scores, load_index, save_index
from .extract import ExtractConfig, extract_dependencies, extract_requirements
from .fsutil import atomic_write_text
from .html_report import render_html
from .graph import build_structure, load_graph, save_graph
from .ingest import ChunkConfig, discover, ingest, load_chunks, load_manifest
from .llm import LLM, LLMError
from .progress import emit_event
from .planning import PlanConfig, build_test_plan
from .retrieval import RetrievalConfig, layered_view, retrieve
from .testplan_context import feature_index, fetch_context, requirement_context
from .interfaces import InterfaceConfig, extract_interfaces
from .interfaces import render as render_interfaces
from .registers import RegisterConfig, extract_registers, extraction_signature
from .registers import render as render_registers
from .combined_fetch import step_targets
from .strategy import build_strategy
from .strategy import render as render_strategy
from .testplan_doc import DocConfig, build_evidence_index, build_testplan_doc, load_template, render_markdown, section_context
from .trace import Tracer
from .usage import run_totals, summarize

TRACE_FILE = "trace.jsonl"
GRAPH_FILE = "graph.json"
DENSE_DIR = "dense"
BUILD_STATS = "build_stats.json"
TEST_PLAN = "test_plan.json"
TESTPLAN_DOC = "testplan_doc.json"
TESTPLAN_MD = "testplan_doc.md"
TESTPLAN_HTML = "testplan_doc.html"
REGISTERS_JSON = "registers.json"
REGISTERS_MD = "registers.md"
INTERFACES_JSON = "interfaces.json"
INTERFACES_MD = "interfaces.md"
STRATEGY_JSON = "strategy.json"
STRATEGY_MD = "strategy.md"
STEP_FILES = (REGISTERS_JSON, REGISTERS_MD, INTERFACES_JSON, INTERFACES_MD, STRATEGY_JSON, STRATEGY_MD)
DERIVED_FILES = (GRAPH_FILE, BUILD_STATS, TEST_PLAN, DENSE_DIR, TESTPLAN_DOC, TESTPLAN_MD, TESTPLAN_HTML) + STEP_FILES
RUN_MARKERS = ("manifest.json", BUILD_STATS, GRAPH_FILE, TRACE_FILE)


def _trace_info(tracer: Tracer) -> dict:
    return dict(trace_id=tracer.trace_id, langfuse=tracer.langfuse_active,
                langfuse_error=tracer.langfuse_error, trace_url=tracer.trace_url(),
                usage=run_totals(tracer.sink, tracer.trace_id))


def _doc_state(docs) -> dict[str, tuple[str, str]]:
    return {d.path: (d.sha256, d.status) for d in docs}


def _ingest_summary(manifest, chunks: int) -> dict:
    return dict(repo=manifest.repo, repo_revision=manifest.repo_revision, chunks=chunks,
                documents=[d.model_dump(include={"doc_id", "path", "status", "reason", "pages"})
                           for d in manifest.documents])


def _ingest_current(repo: Path, out: Path, include: list[str] | None) -> bool:
    if not (out / "manifest.json").exists() or not (out / "chunks.jsonl").exists():
        return False
    saved = load_manifest(out)
    if saved.include != include:
        return False
    return _doc_state(saved.documents) == _doc_state(discover(repo, include))


RUN_ARTIFACTS = ("manifest.json", "chunks.jsonl", "text", GRAPH_FILE, BUILD_STATS,
                 TEST_PLAN, TESTPLAN_DOC, TESTPLAN_MD, TESTPLAN_HTML, *STEP_FILES, DENSE_DIR, "llm_cache", TRACE_FILE)


def _remove(p: Path) -> bool:
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    else:
        return False
    return True


def clear_run(out: Path) -> list[str]:
    """Delete every generated artifact in a run directory (fixed list, nothing else touched).

    Refuses a non-empty directory that has none of the run markers, so a mistyped --out cannot
    delete an unrelated folder's text/ or dense/ directory.
    """
    if not out.exists():
        return []
    if any(out.iterdir()) and not any((out / m).exists() for m in RUN_MARKERS):
        raise ValueError(f"{out} does not look like a dv-agent run directory; refusing to clear it")
    return [name for name in RUN_ARTIFACTS if _remove(out / name)]


def clear_llm_cache(out: Path) -> bool:
    cache = out / "llm_cache"
    if cache.is_dir():
        shutil.rmtree(cache)
        return True
    return False


def _invalidate_derived(out: Path) -> None:
    for name in DERIVED_FILES:
        _remove(out / name)


def run_ingest(repo: Path, out: Path, include: list[str] | None = None,
               cfg: ChunkConfig | None = None, force: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    if not force and _ingest_current(repo, out, include):
        manifest, chunks = load_manifest(out), load_chunks(out)
        return _ingest_summary(manifest, len(chunks)) | {"reused": True, "out": str(out)}
    _invalidate_derived(out)
    with Tracer(out / TRACE_FILE, "ingest", input={"repo": str(repo), "include": include}) as tracer:
        manifest, chunks = ingest(repo, out, include, cfg)
        summary = _ingest_summary(manifest, len(chunks))
        tracer.root.update(output=summary)
    return summary | _trace_info(tracer) | {"reused": False}


def _build_reusable(out: Path, mode: str, dense_mode: str) -> dict | None:
    stats_path = out / BUILD_STATS
    if not (stats_path.exists() and (out / GRAPH_FILE).exists()):
        return None
    try:
        prev = json.loads(stats_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if prev.get("mode") != mode or prev.get("dense_mode") != dense_mode:
        return None
    if prev.get("llm", {}).get("status") not in ("PASS", "NOT_RUN"):
        return None
    # A build with failed chunks or groups is incomplete; rebuild so the cache can fill the gaps.
    if prev.get("requirements", {}).get("failed_chunks") or prev.get("dependencies", {}).get("failed_groups"):
        return None
    if prev.get("dense", {}).get("status") == "BLOCKED":
        return None
    return prev | {"reused": True}


def run_build_graph(out: Path, llm: LLM | None, cfg: ExtractConfig | None = None,
                    embedder: Embedder | None = None, force: bool = False) -> dict:
    mode = f"llm:{llm.model}" if llm is not None else "structural"
    dense_mode = f"dense:{embedder.model}" if embedder is not None else "none"
    if not force:
        reused = _build_reusable(out, mode, dense_mode)
        if reused is not None:
            return reused
    for name in (BUILD_STATS, TEST_PLAN, DENSE_DIR, TESTPLAN_DOC, TESTPLAN_MD, TESTPLAN_HTML, *STEP_FILES):
        _remove(out / name)
    manifest, chunks = load_manifest(out), load_chunks(out)
    with Tracer(out / TRACE_FILE, "build_graph",
                input={"repo": manifest.repo, "repo_revision": manifest.repo_revision,
                       "chunks": len(chunks)},
                metadata={"model": getattr(llm, "model", None)}) as tracer:
        G = build_structure(manifest, chunks)
        stats: dict = {}
        if llm is None:
            stats["llm"] = {"status": "NOT_RUN", "reason": "no LLM configured (MODEL_API_KEY unset)"}
        else:
            try:
                stats["requirements"] = extract_requirements(G, llm, tracer, cfg)
                stats["dependencies"] = extract_dependencies(G, llm, tracer, cfg)
                incomplete = bool(stats["requirements"].get("failed_chunks") or stats["dependencies"].get("failed_groups"))
                stats["llm"] = {"status": "BLOCKED" if incomplete else "PASS", "model": llm.model}
                if incomplete:
                    stats["llm"]["reason"] = "partial extraction; failed source chunks or dependency groups"
            except LLMError as exc:
                stats["llm"] = {"status": "BLOCKED", "reason": exc.kind, "model": llm.model}
        stats["mode"], stats["dense_mode"] = mode, dense_mode
        stats["owners"] = add_owner_edges(G)
        stats["communities"] = build_communities(G)
        if embedder is None:
            stats["dense"] = {"status": "NOT_RUN", "reason": "no embedder configured"}
        else:
            try:
                ids, matrix = build_index(G, embedder)
                save_index(out / DENSE_DIR, embedder.model, ids, matrix)
                stats["dense"] = {"status": "PASS", "model": embedder.model, "vectors": len(ids),
                                  "dim": int(matrix.shape[1])}
            except Exception as exc:
                stats["dense"] = {"status": "BLOCKED", "reason": type(exc).__name__}
        counts: dict[str, int] = {}
        for _, n in G.nodes(data=True):
            counts[n["type"]] = counts.get(n["type"], 0) + 1
        stats["nodes"] = counts
        stats["edges"] = G.number_of_edges()
        G.graph["build_trace_id"] = tracer.trace_id
        save_graph(G, out / GRAPH_FILE)
        tracer.root.update(output=stats)
    stats |= _trace_info(tracer) | {"reused": False}
    atomic_write_text(out / BUILD_STATS, json.dumps(stats, indent=2))
    return stats


def _load_dense(out: Path, embedder: Embedder | None):
    if embedder is None or not (out / DENSE_DIR / "index.json").exists():
        return None
    model, ids, matrix = load_index(out / DENSE_DIR)
    if model != embedder.model:
        raise ValueError(f"dense index built with {model}, embedder is {embedder.model}")
    return ids, matrix


def run_query(out: Path, query: str, cfg: RetrievalConfig | None = None,
              embedder: Embedder | None = None) -> dict:
    G = load_graph(out / GRAPH_FILE)
    index = _load_dense(out, embedder)
    with Tracer(out / TRACE_FILE, "query", input={"query": query}) as tracer:
        with tracer.span("retrieve", as_type="retriever", input={"query": query}) as span:
            dense = dense_scores(embedder, *index, query) if index else None
            result = retrieve(G, query, cfg, dense=dense)
            span.update(output={"evidence": [{k: e[k] for k in ("chunk_id", "score", "section",
                                                                  "explanation")}
                                             for e in result["evidence"]],
                                "requirements": [r["req_id"] for r in result["requirements"]]})
    return result | dict(dense="PASS" if dense is not None else "NOT_RUN") | _trace_info(tracer)


def run_context(out: Path, *, topic: str | None = None, requirement: str | None = None,
                cfg: RetrievalConfig | None = None, embedder: Embedder | None = None,
                global_communities: int | None = None) -> dict:
    """Cited evidence bundle for a test-plan topic or a single requirement (no LLM calls)."""
    if (topic is None) == (requirement is None):
        raise ValueError("give exactly one of topic or requirement")
    G = load_graph(out / GRAPH_FILE)
    H = layered_view(G)
    index = _load_dense(out, embedder)
    query = topic if topic is not None else G.nodes[requirement]["statement"] if (
        requirement in G and G.nodes[requirement].get("type") == "requirement") else None
    with Tracer(out / TRACE_FILE, "context", input={"topic": topic, "requirement": requirement}) as tracer:
        dense = dense_scores(embedder, *index, query) if index and query else None
        if topic is not None:
            bundle = fetch_context(G, topic, cfg=cfg, H=H, dense=dense, tracer=tracer,
                                   global_communities=global_communities)
        else:
            bundle = requirement_context(G, requirement, cfg=cfg, H=H, dense=dense, tracer=tracer)
    return bundle | _trace_info(tracer)


def run_deps(out: Path, requirement_ids: list[str], max_depth: int = 4) -> dict:
    """Dependency closure and precondition-first order for requirements (no model calls)."""
    G = load_graph(out / GRAPH_FILE)
    unknown = [r for r in requirement_ids if r not in G or G.nodes[r].get("type") != "requirement"]
    if unknown:
        raise KeyError(f"unknown requirement IDs: {unknown}")
    ordering = dependency_order(G, requirement_ids, max_depth)
    return dict(requirements=requirement_ids, closure=dependency_closure(G, requirement_ids, max_depth),
                order=[dict(req_id=r, statement=G.nodes[r]["statement"]) for r in ordering["order"]],
                cycles=ordering["cycles"], conflicts=ordering["conflicts"], edges=ordering["edges"])


def run_features(out: Path) -> dict:
    return feature_index(load_graph(out / GRAPH_FILE))


def run_test_plan(out: Path, requirement_ids: list[str], llm: LLM, cfg: PlanConfig,
                  embedder: Embedder | None = None, force: bool = False) -> dict:
    plan_path = out / TEST_PLAN
    dense_state = "PASS" if _load_dense(out, embedder) is not None else "NOT_RUN"
    if not force and plan_path.exists():
        try:
            prev = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
        if (prev.get("requirements") == requirement_ids and prev.get("dense") == dense_state
                and prev.get("model") == llm.model and not any("error" in i for i in prev.get("items", []))):
            return prev | {"reused": True}
    G = load_graph(out / GRAPH_FILE)
    H = layered_view(G)
    index = _load_dense(out, embedder)
    with Tracer(out / TRACE_FILE, "test_plan", input={"requirements": requirement_ids},
                metadata={"model": llm.model}) as tracer:
        items = build_test_plan(G, H, llm, tracer, requirement_ids, cfg, embedder, index)
        save_graph(G, out / GRAPH_FILE)
        plan = dict(trace_id=tracer.trace_id, requirements=requirement_ids, model=llm.model,
                    dense="PASS" if index is not None else "NOT_RUN", items=items)
        tracer.root.update(output={"items": [i.get("id", i.get("error")) for i in items]})
    atomic_write_text(plan_path, json.dumps(plan, indent=2, default=str))
    return plan | _trace_info(tracer) | {"reused": False}


def _doc_summary(doc: dict, out: Path) -> dict:
    return dict(json=str(out / TESTPLAN_DOC), markdown=str(out / TESTPLAN_MD), html=str(out / TESTPLAN_HTML), template_id=doc["template_id"],
                scope=doc["scope"], model=doc["model"], review_status=doc["review_status"],
                doc_trace_id=doc["trace_id"],
                token_usage={k: {x: v["totals"][x] for x in ("calls", "api_calls", "local_cache_hits", "repair_calls",
                                                             "consumed")}
                             for k, v in (doc.get("token_usage") or {}).items()},
                interfaces=None if doc.get("interfaces") is None else dict(
                    status=doc["interfaces"]["status"], groups=[
                        dict(name=g["name"], category=g["category"], sideband=g["is_sideband"],
                             signals=len(g["signals"])) for g in doc["interfaces"]["groups"]]),
                registers=None if doc.get("registers") is None else dict(
                    status=doc["registers"]["status"], registers=len(doc["registers"]["registers"]),
                    configurable_fields=len(doc["registers"].get("configurable", [])),
                    configurable_registers=sorted({f["register"] for f in doc["registers"].get("configurable", [])}),
                    conflicts=len(doc["registers"]["conflicts"])),
                coverage=None if not doc.get("coverage") else dict(
                    total=doc["coverage"]["total"], covered=doc["coverage"]["covered"], ratio=doc["coverage"]["ratio"],
                    uncovered=[r["req_id"] for r in doc["coverage"]["uncovered"]]),
                sections=[dict(id=s["id"], status=s["status"], items=len(
                    s.get("entries") or s.get("configurations") or s.get("register_labels") or s.get("details") or []))
                          for s in doc["sections"]])


def run_testplan_doc(out: Path, llm: LLM, *, scope: str = "", template_path: Path | None = None,
                     cfg: DocConfig | None = None, embedder: Embedder | None = None,
                     force: bool = False, rtl_graph_path: Path | None = None, rtl_scope: str = "") -> dict:
    """Generate the template-driven test-plan document (JSON + Markdown + HTML) from the graph."""
    template = load_template(template_path)
    rtl_graph, rtl_input = None, None
    if rtl_scope and rtl_graph_path is None:
        raise ValueError("rtl_scope requires an explicit RTL graph")
    if rtl_graph_path is not None:
        if not rtl_graph_path.is_file():
            raise ValueError(f"RTL graph not found: {rtl_graph_path}")
        if not any(s["generator"] == "rtl_observations" for s in template["sections"]):
            raise ValueError("template needs an rtl_observations section to use an RTL graph")
        from rtl_agent.graph import load_graph as load_rtl_graph
        from rtl_agent.dense import fingerprint
        rtl_graph = load_rtl_graph(rtl_graph_path)
        if rtl_scope and not any(d.get("type") == "instance" and d.get("scope") == rtl_scope for _, d in rtl_graph.nodes(data=True)):
            raise ValueError(f"unknown RTL scope: {rtl_scope}")
        rtl_input = dict(graph_fingerprint=fingerprint(rtl_graph), scope=rtl_scope, graph_path=str(rtl_graph_path.resolve()))
    G = load_graph(out / GRAPH_FILE)
    doc_path = out / TESTPLAN_DOC
    if not force and doc_path.exists():
        try:
            prev = json.loads(doc_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
        if (prev.get("template_hash") == template["template_hash"] and prev.get("scope") == scope.strip()
                and prev.get("model") == llm.model
                and prev.get("graph_build_trace_id") == G.graph.get("build_trace_id")
                and prev.get("rtl_input") == rtl_input
                and (prev.get("registers") is None or prev["registers"].get("extraction_signature") == extraction_signature())
                and all(s["status"] == "PASS" or (s.get("generator") == "rtl_observations" and s["status"] == "NOT_RUN")
                        for s in prev.get("sections", [])) and prev.get("sections")
                and (prev.get("interfaces") is None or prev["interfaces"]["status"] in ("PASS", "NOT_RUN"))
                and (prev.get("registers") is None or prev["registers"]["status"] in ("PASS", "NOT_RUN"))):
            emit_event("substeps_reused")
            _write_doc_views(prev, out, preserve_markdown=True)
            return _doc_summary(prev, out) | {"reused": True}
    H = layered_view(G)
    index = _load_dense(out, embedder)
    dense_fn = (lambda q: dense_scores(embedder, index[0], index[1], q)) if index else None
    with Tracer(out / TRACE_FILE, "testplan_doc",
                input={"template": template["template_id"], "scope": scope},
                metadata={"model": llm.model}) as tracer:
        doc = build_testplan_doc(G, H, llm, tracer, template, scope, cfg, dense_fn,
                                rtl_graph=rtl_graph, rtl_scope=rtl_scope)
        save_graph(G, out / GRAPH_FILE)
    doc["rtl_input"] = rtl_input
    doc["token_usage"] = {"Test-plan run": summarize(out / TRACE_FILE, tracer.trace_id)}
    if G.graph.get("build_trace_id"):
        doc["token_usage"]["Graph build"] = summarize(out / TRACE_FILE, G.graph["build_trace_id"])
    doc["evidence_index"] = build_evidence_index(G, doc)
    atomic_write_text(doc_path, json.dumps(doc, indent=2, default=str))
    _write_doc_views(doc, out)
    return _doc_summary(doc, out) | _trace_info(tracer) | {"reused": False}


def _write_doc_views(doc: dict, out: Path, *, preserve_markdown: bool = False) -> None:
    emit_event("substep_start", id="render_views", label="Render Markdown and HTML reports")
    if not doc.get("evidence_index") and (out / GRAPH_FILE).is_file():
        doc["evidence_index"] = build_evidence_index(load_graph(out / GRAPH_FILE), doc)
    md_path = out / TESTPLAN_MD
    if preserve_markdown and md_path.exists():
        markdown = md_path.read_text(encoding="utf-8")
    else:
        markdown = render_markdown(doc)
        atomic_write_text(md_path, markdown)
    atomic_write_text(out / TESTPLAN_HTML, render_html(markdown))
    emit_event("substep_done", id="render_views", status="PASS")


def render_testplan(out: Path) -> dict:
    """Refresh HTML from editable Markdown; fall back to saved JSON if needed."""
    if (out / TESTPLAN_MD).is_file():
        markdown = (out / TESTPLAN_MD).read_text(encoding="utf-8")
        atomic_write_text(out / TESTPLAN_HTML, render_html(markdown))
    elif (out / TESTPLAN_DOC).is_file():
        _write_doc_views(json.loads((out / TESTPLAN_DOC).read_text(encoding="utf-8")), out)
    else:
        raise ValueError(f"{out} has no {TESTPLAN_MD} or {TESTPLAN_DOC} to render")
    return dict(markdown=str(out / TESTPLAN_MD), html=str(out / TESTPLAN_HTML))


def run_registers(out: Path, llm: LLM, *, scope: str = "", embedder: Embedder | None = None,
                  force: bool = False) -> dict:
    """Fetch the register map definitions from the specification into registers.json / registers.md."""
    G = load_graph(out / GRAPH_FILE)
    path = out / REGISTERS_JSON
    prev = None if force else _load_current(path, scope.strip(), llm.model, G,
                                          extra={"extraction_signature": extraction_signature()})
    if prev is not None:
        return _registers_summary(prev, out) | {"reused": True}
    H = layered_view(G)
    index = _load_dense(out, embedder)
    dense_fn = (lambda q: dense_scores(embedder, index[0], index[1], q)) if index else None
    with Tracer(out / TRACE_FILE, "registers", input={"scope": scope}, metadata={"model": llm.model}) as tracer:
        result = extract_registers(G, H, llm, tracer, scope.strip(), RegisterConfig(), dense_fn)
        tracer.root.update(output={"status": result["status"], "registers": len(result["registers"])})
    result |= dict(scope=scope.strip(), model=llm.model, graph_build_trace_id=G.graph.get("build_trace_id"),
                   trace_id=tracer.trace_id)
    atomic_write_text(path, json.dumps(result, indent=2, default=str))
    atomic_write_text(out / REGISTERS_MD, "\n".join(render_registers(result, "Register Map")))
    return _registers_summary(result, out) | _trace_info(tracer) | {"reused": False}


def _registers_summary(result: dict, out: Path) -> dict:
    return dict(json=str(out / REGISTERS_JSON), markdown=str(out / REGISTERS_MD), status=result["status"],
                step_trace_id=result["trace_id"],
                registers=[dict(name=r["name"], abbreviation=r["abbreviation"], address=r["address"],
                                fields=len(r["fields"]), provenance=r["provenance"]) for r in result["registers"]],
                configurable_fields=len(result.get("configurable", [])),
                configurable_registers=sorted({f["register"] for f in result.get("configurable", [])}),
                conflicts=result["conflicts"],
                validation=result["validation"], failed_batches=result["failed_batches"])


STRATEGY_QUERIES = ["{scope} bus interface signals", "{scope} external interface signals", "{scope} interrupts reset",
                    "{scope} test or loopback modes", "{scope} data transfer"]


def _load_current(path: Path, scope: str, model: str, G, extra: dict | None = None) -> dict | None:
    if not path.exists():
        return None
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    ok = (prev.get("scope") == scope and prev.get("model") == model
          and prev.get("graph_build_trace_id") == G.graph.get("build_trace_id")
          and prev.get("status") in ("PASS", "NOT_RUN")
          and all(prev.get(k) == v for k, v in (extra or {}).items()))
    return prev if ok else None


def _dense_fn(out: Path, embedder: Embedder | None):
    index = _load_dense(out, embedder)
    return (lambda q: dense_scores(embedder, index[0], index[1], q)) if index else None


def run_interfaces(out: Path, llm: LLM, *, scope: str = "", embedder: Embedder | None = None,
                   force: bool = False) -> dict:
    """Isolate and group interface definitions into interfaces.json / interfaces.md."""
    G = load_graph(out / GRAPH_FILE)
    scope = scope.strip()
    prev = None if force else _load_current(out / INTERFACES_JSON, scope, llm.model, G)
    if prev is not None:
        return _interfaces_summary(prev, out) | {"reused": True}
    with Tracer(out / TRACE_FILE, "interfaces", input={"scope": scope}, metadata={"model": llm.model}) as tracer:
        result = extract_interfaces(G, layered_view(G), llm, tracer, scope, InterfaceConfig(), _dense_fn(out, embedder))
        tracer.root.update(output={"status": result["status"], "groups": len(result["groups"])})
    result |= dict(scope=scope, model=llm.model, graph_build_trace_id=G.graph.get("build_trace_id"),
                   trace_id=tracer.trace_id)
    atomic_write_text(out / INTERFACES_JSON, json.dumps(result, indent=2, default=str))
    atomic_write_text(out / INTERFACES_MD, "\n".join(render_interfaces(result, "Interface Definitions")))
    return _interfaces_summary(result, out) | _trace_info(tracer) | {"reused": False}


def _interfaces_summary(result: dict, out: Path) -> dict:
    return dict(json=str(out / INTERFACES_JSON), markdown=str(out / INTERFACES_MD), status=result["status"],
                step_trace_id=result["trace_id"],
                groups=[dict(name=g["name"], category=g["category"], peer_type=g["peer_type"],
                             sideband=g["is_sideband"], signals=[s["name"] for s in g["signals"]])
                        for g in result["groups"]], validation=result["validation"])


def run_strategy(out: Path, llm: LLM, *, scope: str = "", embedder: Embedder | None = None,
                 force: bool = False) -> dict:
    """Verification strategy built from the documented interface and register steps."""
    scope = scope.strip()
    ifs = run_interfaces(out, llm, scope=scope, embedder=embedder)
    regs = run_registers(out, llm, scope=scope, embedder=embedder)
    interfaces = json.loads((out / INTERFACES_JSON).read_text(encoding="utf-8"))
    registers = json.loads((out / REGISTERS_JSON).read_text(encoding="utf-8"))
    G = load_graph(out / GRAPH_FILE)
    inputs = dict(interfaces_trace_id=interfaces["trace_id"], registers_trace_id=registers["trace_id"])
    prev = None if force else _load_current(out / STRATEGY_JSON, scope, llm.model, G, inputs)
    if prev is not None:
        return _strategy_summary(prev, out) | {"reused": True, "inputs": dict(interfaces=ifs["reused"], registers=regs["reused"])}
    H = layered_view(G)
    dense_fn = _dense_fn(out, embedder)
    with Tracer(out / TRACE_FILE, "strategy", input={"scope": scope} | inputs, metadata={"model": llm.model}) as tracer:
        ctx = section_context(G, H, {"queries": STRATEGY_QUERIES}, scope, DocConfig(), dense_fn,
                              targets=step_targets(G, interfaces, registers), tracer=tracer)
        result = build_strategy(llm, tracer, interfaces, registers, scope, ctx)
        tracer.root.update(output={"status": result["status"], "agents": len(result["agents"])},
                           metadata={"chunk_ids": sorted({c for a in result["agents"] for c in a["cited_chunk_ids"]})})
    result |= dict(scope=scope, model=llm.model, graph_build_trace_id=G.graph.get("build_trace_id"),
                   trace_id=tracer.trace_id, **inputs)
    atomic_write_text(out / STRATEGY_JSON, json.dumps(result, indent=2, default=str))
    atomic_write_text(out / STRATEGY_MD, "\n".join(render_strategy(result, "High Level Verification Strategy")))
    return (_strategy_summary(result, out) | _trace_info(tracer)
            | {"reused": False, "inputs": dict(interfaces=ifs["reused"], registers=regs["reused"])})


def _strategy_summary(result: dict, out: Path) -> dict:
    return dict(json=str(out / STRATEGY_JSON), markdown=str(out / STRATEGY_MD), status=result["status"],
                error=result.get("error"),
                agents=[dict(name=a["name"], mode=a["mode"], interface_groups=a["interface_groups"],
                             registers=a["registers"]) for a in result["agents"]],
                scoreboards=[dict(name=s["name"], level=s["level"], inputs=s["inputs"]) for s in result["scoreboards"]],
                gaps=result["gaps"], validation=result["validation"])


def run_usage(out: Path, trace_id: str | None = None, last: int | None = None) -> dict:
    """Token totals per run and per model call, from the run directory's trace."""
    summary = summarize(out / TRACE_FILE, trace_id)
    if last:
        summary["runs"] = summary["runs"][-last:]
    return summary
