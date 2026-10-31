"""Explicit graph CLI, available only in rtl_agent (never in the spec pipeline)."""
import json
from pathlib import Path

from .builder import write_artifacts
from .commands import _assignments, _read_json
from .source import RTLExtractionError


def add_graph_commands(sub):
    build = sub.add_parser("build-graph", help="build source-backed RTL hierarchy/dependency/domain graph")
    build.add_argument("files", type=Path, nargs="+")
    build.add_argument("--top", required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("-I", "--include-dir", type=Path, action="append", default=[])
    build.add_argument("-D", "--define", action="append", default=[])
    build.add_argument("-P", "--parameter", action="append", default=[])
    build.add_argument("--features", type=Path, help="explicit feature labels and hierarchy targets (JSON)")
    build.add_argument("--max-instances", type=int, default=256)
    for name in ("query", "context"):
        query = sub.add_parser(name, help="fetch a ranked, cited RTL graph context bundle")
        query.add_argument("text")
        query.add_argument("--graph", type=Path, required=True)
        query.add_argument("--scope", default="", help="exact instance scope; includes descendants")
        query.add_argument("--top-k", type=int, default=16)
        query.add_argument("--hops", type=int, default=3)
        query.add_argument("--max-expansions", type=int, default=256)
        query.add_argument("--save", type=Path)
        query.add_argument("--dense-index", type=Path)
        query.add_argument("--query-vector", type=Path, help="JSON with model and vector (same embedding model)")
    info = sub.add_parser("graph-info", help="graph statistics, clock/reset domains and unsupported analysis gaps")
    info.add_argument("--graph", type=Path, required=True)
    index = sub.add_parser("index-graph", help="validate/index externally computed embeddings for this graph")
    index.add_argument("--graph", type=Path, required=True)
    index.add_argument("--embeddings", type=Path, required=True, help="JSON with model and node-ID vectors")
    index.add_argument("--out", type=Path, required=True)
    spec = sub.add_parser("build-spec", help="draft a review-required specification from a saved RTL graph")
    spec.add_argument("--graph", type=Path, required=True)
    spec.add_argument("--out", type=Path, required=True)
    spec.add_argument("--template", type=Path, help="Generic RTL specification template JSON")


def _write(G, path: Path, obj: dict, protected: list[Path]):
    write_artifacts(path.parent, {path.name: json.dumps(obj, indent=2) + "\n"},
                    protected=protected + [Path(s["path"]) for s in G.graph["sources"]])


def run_graph_command(args):
    try:
        if args.cmd == "build-spec":
            from .specification import build_specification
            return build_specification(args.graph, args.out, args.template)
        from .graph import BuildConfig, build_graph, load_graph, save_graph
        from .retrieval import QueryConfig, fetch_context
        if args.cmd == "build-graph":
            G = build_graph(args.files, args.top, include_dirs=args.include_dir,
                            defines=_assignments(args.define, define=True),
                            overrides=_assignments(args.parameter, define=False),
                            features=_read_json(args.features) if args.features else None,
                            cfg=BuildConfig(max_instances=args.max_instances))
            path = args.out / "rtl_graph.json"
            if args.features and path.resolve() == args.features.resolve():
                raise RTLExtractionError("refusing to overwrite feature annotations with graph output")
            save_graph(G, path)
            return dict(graph=str(path), analysis_status=G.graph["analysis_status"],
                        statistics=G.graph["statistics"], diagnostics=len(G.graph["diagnostics"]))
        G = load_graph(args.graph)
        if args.cmd == "graph-info":
            return dict(top=G.graph["top"], analysis_status=G.graph["analysis_status"],
                        statistics=G.graph["statistics"], domains=G.graph["domains"],
                        crossings=G.graph.get("domain_crossings", []), diagnostics=G.graph["diagnostics"])
        if args.cmd == "index-graph":
            from .dense import make_index
            if args.embeddings.stat().st_size > 64 * 1024 * 1024:
                raise RTLExtractionError("embedding input exceeds the 64 MiB budget")
            data = _read_json(args.embeddings)
            index = make_index(G, data["model"], data["vectors"])
            path = args.out / "rtl_dense_index.json"
            _write(G, path, index, [args.graph, args.embeddings])
            return dict(index=str(path), model=index["model"], dimension=index["dimension"], vectors=len(index["vectors"]))
        if bool(args.dense_index) != bool(args.query_vector):
            raise RTLExtractionError("--dense-index and --query-vector must be supplied together")
        scores = None
        if args.dense_index:
            from .dense import dense_scores
            if args.dense_index.stat().st_size > 64 * 1024 * 1024 or args.query_vector.stat().st_size > 256 * 1024:
                raise RTLExtractionError("dense index or query vector exceeds its input budget")
            query = _read_json(args.query_vector)
            scores = dense_scores(G, _read_json(args.dense_index), query["vector"], model=query["model"])
        result = fetch_context(G, args.text, scope=args.scope, dense=scores,
                               cfg=QueryConfig(top_k=args.top_k, hops=args.hops, max_expansions=args.max_expansions))
        if args.save:
            _write(G, args.save, result, [p for p in (args.graph, args.dense_index, args.query_vector) if p])
        return result
    except (OSError, KeyError, TypeError, IndexError) as exc:
        raise RTLExtractionError(f"invalid graph input/output: {exc}") from exc
