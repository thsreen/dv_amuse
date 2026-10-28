"""Pipeline stages, each wrapped in its own trace."""
import json
import shutil
from pathlib import Path

from .community import build_communities
from .dense import Embedder, build_index, dense_scores, load_index, save_index
from .extract import ExtractConfig, extract_dependencies, extract_requirements
from .fsutil import atomic_write_text
from .graph import build_structure, load_graph, save_graph
from .ingest import ChunkConfig, discover, ingest, load_chunks, load_manifest
from .llm import LLM, LLMError
from .planning import PlanConfig, build_test_plan
from .retrieval import RetrievalConfig, layered_view, retrieve
from .testplan_context import feature_index, fetch_context, requirement_context
from .testplan_doc import DocConfig, build_testplan_doc, load_template, render_markdown
from .trace import Tracer

TRACE_FILE = "trace.jsonl"
GRAPH_FILE = "graph.json"
DENSE_DIR = "dense"
BUILD_STATS = "build_stats.json"
TEST_PLAN = "test_plan.json"
TESTPLAN_DOC = "testplan_doc.json"
TESTPLAN_MD = "testplan_doc.md"
DERIVED_FILES = (GRAPH_FILE, BUILD_STATS, TEST_PLAN, DENSE_DIR, TESTPLAN_DOC, TESTPLAN_MD)
RUN_MARKERS = ("manifest.json", BUILD_STATS, GRAPH_FILE, TRACE_FILE)


def _trace_info(tracer: Tracer) -> dict:
    return dict(trace_id=tracer.trace_id, langfuse=tracer.langfuse_active,
                langfuse_error=tracer.langfuse_error, trace_url=tracer.trace_url())


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
                 TEST_PLAN, TESTPLAN_DOC, TESTPLAN_MD, DENSE_DIR, "llm_cache", TRACE_FILE)


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
    for name in (BUILD_STATS, TEST_PLAN, DENSE_DIR, TESTPLAN_DOC, TESTPLAN_MD):
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
                stats["llm"] = {"status": "PASS", "model": llm.model}
            except LLMError as exc:
                stats["llm"] = {"status": "BLOCKED", "reason": exc.kind, "model": llm.model}
        stats["mode"], stats["dense_mode"] = mode, dense_mode
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
                cfg: RetrievalConfig | None = None, embedder: Embedder | None = None) -> dict:
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
            bundle = fetch_context(G, topic, cfg=cfg, H=H, dense=dense, tracer=tracer)
        else:
            bundle = requirement_context(G, requirement, cfg=cfg, H=H, dense=dense, tracer=tracer)
    return bundle | _trace_info(tracer)


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
    return dict(json=str(out / TESTPLAN_DOC), markdown=str(out / TESTPLAN_MD), template_id=doc["template_id"],
                scope=doc["scope"], model=doc["model"], review_status=doc["review_status"],
                doc_trace_id=doc["trace_id"],
                interfaces=None if doc.get("interfaces") is None else dict(
                    status=doc["interfaces"]["status"], groups=[
                        dict(name=g["name"], category=g["category"], sideband=g["is_sideband"],
                             signals=len(g["signals"])) for g in doc["interfaces"]["groups"]]),
                sections=[dict(id=s["id"], status=s["status"],
                               items=len(s.get("entries", s.get("registers", s.get("details", [])))))
                          for s in doc["sections"]])


def run_testplan_doc(out: Path, llm: LLM, *, scope: str = "", template_path: Path | None = None,
                     cfg: DocConfig | None = None, embedder: Embedder | None = None,
                     force: bool = False) -> dict:
    """Generate the template-driven test-plan document (JSON + Markdown) from the graph."""
    template = load_template(template_path)
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
                and all(s["status"] == "PASS" for s in prev.get("sections", [])) and prev.get("sections")
                and (prev.get("interfaces") is None or prev["interfaces"]["status"] in ("PASS", "NOT_RUN"))):
            return _doc_summary(prev, out) | {"reused": True}
    H = layered_view(G)
    index = _load_dense(out, embedder)
    dense_fn = (lambda q: dense_scores(embedder, index[0], index[1], q)) if index else None
    with Tracer(out / TRACE_FILE, "testplan_doc",
                input={"template": template["template_id"], "scope": scope},
                metadata={"model": llm.model}) as tracer:
        doc = build_testplan_doc(G, H, llm, tracer, template, scope, cfg, dense_fn)
        save_graph(G, out / GRAPH_FILE)
    atomic_write_text(doc_path, json.dumps(doc, indent=2, default=str))
    atomic_write_text(out / TESTPLAN_MD, render_markdown(doc))
    return _doc_summary(doc, out) | _trace_info(tracer) | {"reused": False}
