"""Fetch knowledge from the RAG graph for building verification test plans.

Template-independent: bundles have a stable, versioned shape so a test-plan template can map its
fields onto them. Bundles are built from specification-derived graph nodes only. Every item carries its citation; L3 summaries are returned separately and flagged as
navigation only. Extend by adding fields to `_bundle` and bumping BUNDLE_SCHEMA_VERSION.
"""
import re

import networkx as nx

from .graph import DEPENDENCY_EDGES, edges_of_type, lineage
from .retrieval import RetrievalConfig, retrieve
from .trace import Tracer

BUNDLE_SCHEMA_VERSION = 1
MAX_REQUIREMENTS = 15


def requirement_record(G: nx.MultiDiGraph, rid: str) -> dict:
    n = G.nodes[rid]
    return dict(req_id=rid, statement=n["statement"], quote=n["quote"], kind=n["kind"],
                status=n["status"], interpretation=n.get("interpretation", "INFERRED"),
                review_status=n["review_status"],
                citation=dict(doc_path=n["doc_path"], page=n["page"], section=n["section"],
                              chunk_id=n["chunk_id"], quote_start=n.get("quote_start"),
                              quote_end=n.get("quote_end")))


def chunk_record(G: nx.MultiDiGraph, cid: str) -> dict:
    n = G.nodes[cid]
    return dict(chunk_id=cid, doc_path=n["doc_path"], pages=[n["page_start"], n["page_end"]],
                section=" > ".join(n["section_path"]), text=n["text"], text_sha256=n["text_sha256"])


def dependencies_of(G: nx.MultiDiGraph, req_ids: set[str]) -> list[dict]:
    """Dependency edges touching any of the requirements, in both directions, deduplicated."""
    seen, out = set(), []
    for rid in sorted(req_ids):
        for u, v, etype, data in (edges_of_type(G, rid, DEPENDENCY_EDGES)
                                  + edges_of_type(G, rid, DEPENDENCY_EDGES, out=False)):
            if (u, etype, v) in seen:
                continue
            seen.add((u, etype, v))
            out.append(dict(src=u, type=etype, dst=v, status=data.get("status", "INFERRED"),
                            review_status=data.get("review_status", "NOT_REVIEWED"),
                            rationale=data.get("rationale", ""),
                            evidence_quote=data.get("evidence_quote", ""),
                            src_in_scope=u in req_ids, dst_in_scope=v in req_ids))
    return out


def _entities(G: nx.MultiDiGraph, req_ids: set[str]) -> list[dict]:
    found: dict[str, set[str]] = {}
    for rid in req_ids:
        for _, eid, _, _ in edges_of_type(G, rid, {"MENTIONS"}):
            found.setdefault(eid, set()).add(rid)
    return [dict(entity_id=e, name=G.nodes[e]["name"], kind=G.nodes[e]["kind"],
                 aliases=G.nodes[e]["aliases"], requirements=sorted(found[e]))
            for e in sorted(found, key=lambda e: (-len(found[e]), G.nodes[e]["name"]))]


def _navigation(G: nx.MultiDiGraph, chunk_ids: list[str], req_ids: set[str]) -> list[dict]:
    nav: dict[str, dict] = {}
    for cid in chunk_ids:
        for _, sid, _, _ in edges_of_type(G, cid, {"PART_OF"}):
            s = G.nodes[sid]
            if s.get("type") == "section" and s.get("summaries"):
                nav[sid] = dict(node_id=sid, type="section", title=s["title"],
                                summary=" ".join(s["summaries"]), navigation_only=True)
    for rid in req_ids:
        for _, com, _, _ in edges_of_type(G, rid, {"MEMBER_OF"}):
            c = G.nodes[com]
            nav[com] = dict(node_id=com, type="community", title=c["label"], summary=c["summary"],
                            navigation_only=True)
    return [nav[k] for k in sorted(nav)]


def _open_items(reqs: list[dict], deps: list[dict]) -> list[dict]:
    items = [dict(kind="conflict", src=d["src"], dst=d["dst"], rationale=d["rationale"])
             for d in deps if d["type"] == "CONFLICTS_WITH"]
    items += [dict(kind="unreviewed_dependency", src=d["src"], type=d["type"], dst=d["dst"])
              for d in deps if d["type"] != "CONFLICTS_WITH" and d["review_status"] != "APPROVED"]
    unreviewed = [r["req_id"] for r in reqs if r["review_status"] != "APPROVED"]
    if unreviewed:
        items.append(dict(kind="unreviewed_requirements", req_ids=unreviewed))
    return items


def _bundle(G: nx.MultiDiGraph, kind: str, query: str, result: dict, req_ids: list[str],
            extra: dict | None = None) -> dict:
    in_scope = set(req_ids)
    deps = dependencies_of(G, in_scope)
    outside = sorted({d["dst"] for d in deps if not d["dst_in_scope"]}
                     | {d["src"] for d in deps if not d["src_in_scope"]})
    reqs = [requirement_record(G, r) for r in req_ids]
    chunk_ids = [e["chunk_id"] for e in result["evidence"]]
    return dict(
        schema_version=BUNDLE_SCHEMA_VERSION, kind=kind, query=query, authority="specification",
        requirements=reqs,
        dependency_requirements=[requirement_record(G, r) for r in outside],
        dependencies=deps,
        entities=_entities(G, in_scope | set(outside)),
        evidence=[dict(chunk_record(G, e["chunk_id"]), score=e["score"], components=e["components"],
                       explanation=e["explanation"]) for e in result["evidence"]],
        navigation=_navigation(G, chunk_ids, in_scope),
        open_items=_open_items(reqs, deps),
        retrieval=dict(seeds=result["seeds"],
                       dense="PASS" if any(e["components"]["dense"] for e in result["evidence"]) else "NOT_RUN"),
        **(extra or {}))


def _ranked_requirements(result: dict, limit: int) -> list[str]:
    ordered: list[str] = []
    for e in result["evidence"]:
        for r in e["supporting_requirements"]:
            if r not in ordered:
                ordered.append(r)
    for r in result["requirements"]:
        if r["req_id"] not in ordered:
            ordered.append(r["req_id"])
    return ordered[:limit]


def _trace(tracer: Tracer | None, name: str, inputs: dict, bundle: dict) -> None:
    if tracer is None:
        return
    with tracer.span(name, as_type="retriever", input=inputs) as span:
        fact_ids = [r["req_id"] for r in bundle["requirements"] + bundle["dependency_requirements"]]
        span.update(output={"requirements": [r["req_id"] for r in bundle["requirements"]],
                            "dependency_requirements": [r["req_id"] for r in bundle["dependency_requirements"]],
                            "chunks": [e["chunk_id"] for e in bundle["evidence"]],
                            "open_items": len(bundle["open_items"])},
                    metadata={"fact_ids": fact_ids})


def fetch_context(G: nx.MultiDiGraph, topic: str, *, cfg: RetrievalConfig | None = None,
                  H: nx.Graph | None = None, dense: dict[str, float] | None = None,
                  max_requirements: int = MAX_REQUIREMENTS, tracer: Tracer | None = None) -> dict:
    """Evidence bundle for a feature or topic, e.g. one test-plan section."""
    result = retrieve(G, topic, cfg, dense=dense, H=H)
    bundle = _bundle(G, "topic", topic, result, _ranked_requirements(result, max_requirements))
    _trace(tracer, "fetch_context", {"topic": topic}, bundle)
    return bundle


def requirement_context(G: nx.MultiDiGraph, req_id: str, *, cfg: RetrievalConfig | None = None,
                        H: nx.Graph | None = None, dense: dict[str, float] | None = None,
                        max_requirements: int = MAX_REQUIREMENTS, tracer: Tracer | None = None) -> dict:
    """Evidence bundle centred on one requirement, including its lineage."""
    if req_id not in G or G.nodes[req_id].get("type") != "requirement":
        raise KeyError(f"unknown requirement: {req_id}")
    statement = G.nodes[req_id]["statement"]
    result = retrieve(G, statement, cfg, dense=dense, H=H, extra_seeds={req_id: 1.0})
    ranked = [req_id] + [r for r in _ranked_requirements(result, max_requirements) if r != req_id]
    bundle = _bundle(G, "requirement", statement, result, ranked[:max_requirements],
                     extra={"focus_requirement": req_id, "lineage": lineage(G, req_id)})
    _trace(tracer, f"requirement_context:{req_id}", {"req_id": req_id}, bundle)
    return bundle


def _section_key(path: list[str]) -> tuple:
    nums = []
    for part in path:
        m = re.match(r"^(\d+(?:\.\d+)*)\s", part)
        nums.append(tuple(int(x) for x in m.group(1).split(".")) if m else ())
    return tuple(nums)


def feature_index(G: nx.MultiDiGraph) -> dict:
    """Specification outline for driving a test plan: sections and communities with their requirements."""
    sections = []
    for sid, s in G.nodes(data=True):
        if s.get("type") != "section":
            continue
        chunk_ids = sorted(c for c, _, _, _ in edges_of_type(G, sid, {"PART_OF"}, out=False)
                           if G.nodes[c].get("type") == "chunk")
        req_ids = sorted(r for c in chunk_ids for r, _, _, _ in edges_of_type(G, c, {"DERIVED_FROM"}, out=False)
                         if G.nodes[r].get("type") == "requirement")
        ents = sorted({G.nodes[e]["name"] for r in req_ids for _, e, _, _ in edges_of_type(G, r, {"MENTIONS"})})
        sections.append(dict(section_id=sid, doc_id=s["doc_id"], title=s["title"],
                             section_path=s["section_path"], depth=len(s["section_path"]),
                             chunk_ids=chunk_ids, requirement_ids=req_ids, entities=ents))
    sections.sort(key=lambda x: (x["doc_id"], _section_key(x["section_path"]), x["title"]))
    communities = [dict(community_id=c, label=d["label"], summary=d["summary"],
                        requirement_ids=sorted(m for m in d["members"] if G.nodes[m]["type"] == "requirement"),
                        navigation_only=True)
                   for c, d in sorted(G.nodes(data=True)) if d.get("type") == "community"]
    return dict(schema_version=BUNDLE_SCHEMA_VERSION, sections=sections, communities=communities,
                requirements_total=sum(1 for _, d in G.nodes(data=True) if d.get("type") == "requirement"))
