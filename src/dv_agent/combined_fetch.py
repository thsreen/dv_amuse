"""Combined graph fetch used by every test-plan step.

Merges six candidate sources for one topic, each item recording how it was reached:
retrieval (seeds + PageRank), entity (owner/part traversal), dependency (preconditions), global
(community summaries), coverage (requirements not yet cited) and path (shortest paths from the topic's
anchors to the verified signals and registers). The path source is a deliberately small take on the
guided-walk idea from AssertionForge's GRW-AS (ideas only; hackathon scope, D-017). Adaptive selection
gives each source a minimum share so none crowds out the others.
"""
import math
from dataclasses import dataclass, field

import networkx as nx

from .extract import _name_keys, normalize_name
from .graph_fetch import dependency_closure, entity_context, global_fetch, requirement_coverage, resolve_entities
from .retrieval import RetrievalConfig, layered_view, retrieve

SOURCE_TYPES = ("retrieval", "entity", "dependency", "global", "path", "coverage")


@dataclass
class FetchConfig:
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    entity_hops: int = 2
    dependency_depth: int = 3
    global_communities: int = 2
    max_requirements: int = 20
    max_chunks: int = 12
    min_per_source: int = 2
    max_coverage_targets: int = 15
    max_path_targets: int = 15
    max_path_length: int = 6


def step_targets(G: nx.MultiDiGraph, interfaces: dict | None, registers: dict | None) -> list[str]:
    """Graph entities for the verified interface signals and registers (exact name or alias match)."""
    index: dict[str, list[str]] = {}
    for eid, d in G.nodes(data=True):
        if d.get("type") == "entity":
            for k in _name_keys(d["name"], d["aliases"]):
                index.setdefault(k, []).append(eid)
    names = [s["name"] for g in (interfaces or {}).get("groups", []) for s in g["signals"]]
    for r in (registers or {}).get("registers", []):
        names += [r["abbreviation"], r["name"]]
    return sorted({eid for n in names if n for eid in index.get(normalize_name(n), [])})


def target_paths(H: nx.Graph, starts: list[str], targets: list[str], max_targets: int, max_length: int) -> list[dict]:
    """Shortest weighted path from the nearest start to each target (cost = -log edge weight)."""
    starts = [s for s in dict.fromkeys(starts) if s in H]
    if not starts:
        return []
    _, paths = nx.multi_source_dijkstra(H, starts, weight=lambda u, v, d: -math.log(max(d["weight"], 1e-9)))
    found = []
    for t in [t for t in targets if t in paths][:max_targets]:
        if 1 < len(paths[t]) <= max_length:
            found.append(dict(target=t, path=paths[t]))
    return sorted(found, key=lambda p: (len(p["path"]), p["target"]))


def _label(G: nx.MultiDiGraph, n: str) -> str:
    d = G.nodes[n]
    return f"{d.get('type')}:{d.get('name') or d.get('title') or d.get('label') or d.get('statement', '')[:40] or n}"


def combined_fetch(G: nx.MultiDiGraph, topic: str, *, H: nx.Graph | None = None, cfg: FetchConfig | None = None,
                   dense: dict[str, float] | None = None, targets: list[str] | None = None,
                   covered_req_ids: set[str] | None = None, covered_chunk_ids: set[str] | None = None,
                   extra_anchors: list[str] | None = None, extra_seeds: dict[str, float] | None = None) -> dict:
    """All fetch sources for one topic, merged by adaptive selection; every item carries its sources and path."""
    cfg = cfg or FetchConfig()
    H = H if H is not None else layered_view(G)
    anchors = [a["entity_id"] for a in resolve_entities(G, topic)]
    anchors += [a for a in (extra_anchors or []) if a in G and a not in anchors]
    seeds = {a: 1.0 for a in anchors} | (extra_seeds or {})
    result = retrieve(G, topic, cfg.retrieval, dense=dense, H=H, extra_seeds=seeds or None)
    cands: dict[str, list[dict]] = {t: [] for t in SOURCE_TYPES}
    chunk_cands: dict[str, list[dict]] = {t: [] for t in SOURCE_TYPES}

    ranked: list[str] = []
    for e in result["evidence"]:
        chunk_cands["retrieval"].append(dict(chunk_id=e["chunk_id"], score=e["score"], via=e["explanation"]))
        ranked += [r for r in e["supporting_requirements"] if r not in ranked]
    ranked += [r["req_id"] for r in result["requirements"] if r["req_id"] not in ranked]
    cands["retrieval"] = [dict(req_id=r, score=max(0.5, 1.0 - 0.02 * i), via="seed retrieval + PageRank")
                          for i, r in enumerate(ranked)]

    ent = entity_context(G, anchors, hops=cfg.entity_hops, max_requirements=cfg.max_requirements) if anchors else {}
    cands["entity"] = list(ent.get("requirements", []))
    chunk_cands["entity"] = list(ent.get("chunks", []))

    roots = [c["req_id"] for c in cands["retrieval"][:5] + cands["entity"][:5]]
    cands["dependency"] = [dict(req_id=c["req_id"], score=round(0.8 * 0.85 ** c["depth"], 4),
                                via=f"precondition (depth {c['depth']}) of {c['root']}")
                           for c in dependency_closure(G, roots, cfg.dependency_depth)]

    glob = global_fetch(G, topic, top=cfg.global_communities, max_requirements=cfg.max_requirements) \
        if cfg.global_communities else {"communities": [], "requirements": [], "chunks": []}
    cands["global"] = [dict(r, score=round(0.9 * r["score"], 4)) for r in glob["requirements"]]
    chunk_cands["global"] = list(glob["chunks"])

    coverage_targets = []
    if covered_req_ids is not None:
        cov = requirement_coverage(G, covered_req_ids, covered_chunk_ids or set())
        relevant = {c["req_id"] for t in ("retrieval", "entity", "dependency", "global") for c in cands[t]}
        coverage_targets = [r["req_id"] for r in cov["uncovered"] + cov["chunk_only"]
                            if r["req_id"] in relevant][:cfg.max_coverage_targets]
        cands["coverage"] = [dict(req_id=r, score=0.85, via="not yet cited by the plan") for r in coverage_targets]

    path_targets = sorted(set(targets or []) | set(coverage_targets))
    starts = anchors + [s["node"] for s in result["seeds"]]
    paths = target_paths(H, starts, path_targets, cfg.max_path_targets, cfg.max_path_length)
    for p in paths:
        desc = " -> ".join(_label(G, n) for n in p["path"])
        score = round(0.9 ** (len(p["path"]) - 1), 4)
        for n in p["path"]:
            kind = G.nodes[n].get("type")
            if kind == "requirement":
                cands["path"].append(dict(req_id=n, score=score, via=f"path to target: {desc}"))
            elif kind == "chunk":
                chunk_cands["path"].append(dict(chunk_id=n, score=score, via=f"path to target: {desc}"))

    requirements = adaptive_select(cands, "req_id", cfg.max_requirements, cfg.min_per_source)
    for r in requirements:  # each selected requirement's source chunk is evidence too
        chunk_cands[r["source"]].append(
            dict(chunk_id=G.nodes[r["req_id"]]["chunk_id"], score=r["score"], via=f"source of {r['req_id']}"))
    chunks = adaptive_select(chunk_cands, "chunk_id", cfg.max_chunks, cfg.min_per_source)
    return dict(
        topic=topic, result=result, anchors=ent.get("anchors", []), parts=ent.get("parts", []),
        owners=ent.get("owners", []), global_communities=glob["communities"],
        requirements=requirements, chunks=chunks,
        paths=[dict(target=p["target"], length=len(p["path"]) - 1,
                    path=" -> ".join(_label(G, n) for n in p["path"])) for p in paths],
        path_targets=path_targets, coverage_targets=coverage_targets,
        selection={t: sum(1 for r in requirements if t in r["sources"]) for t in SOURCE_TYPES})


def adaptive_select(cands: dict[str, list[dict]], key: str, limit: int, min_per_source: int) -> list[dict]:
    """Each source first gets up to min_per_source of its best items, then the best overall fill the cap.

    An item found by several sources keeps its best score and lists every source in "sources".
    """
    best: dict[str, dict] = {}
    for source in SOURCE_TYPES:
        for c in cands.get(source, []):
            if c[key] not in best:
                best[c[key]] = dict(c, source=source, sources=[source])
                continue
            item = best[c[key]]
            if source not in item["sources"]:
                item["sources"].append(source)
            if c["score"] > item["score"]:
                best[c[key]] = dict(c, source=source, sources=item["sources"])
    chosen: list[str] = []
    for source in SOURCE_TYPES:
        own = sorted((i for i in best.values() if source in i["sources"]), key=lambda i: (-i["score"], i[key]))
        have = sum(1 for k in chosen if source in best[k]["sources"])
        for i in own:
            if have >= min_per_source or len(chosen) >= limit:
                break
            if i[key] not in chosen:
                chosen.append(i[key])
                have += 1
    rest = sorted((i for i in best.values() if i[key] not in chosen), key=lambda i: (-i["score"], i[key]))
    chosen += [i[key] for i in rest[:max(0, limit - len(chosen))]]
    return sorted((best[k] for k in chosen), key=lambda i: (-i["score"], i[key]))
