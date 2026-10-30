"""Three-layer property graph and lineage.

L1 chunk nodes (immutable source text), L2 requirement/entity nodes (derived, quote-backed),
L3 document/section nodes (navigation aids, never sources of truth). Downstream artifacts such as
assertions attach as layer-4 nodes with DERIVED_FROM edges so their lineage can be walked.
"""
import bisect
import hashlib
import json
from pathlib import Path
from typing import Any

import networkx as nx

from .fsutil import atomic_write_text
from .models import Chunk, Manifest
from .trace import Tracer

EDGE_WEIGHTS = {
    "PART_OF": 0.6, "NEXT": 0.3, "DERIVED_FROM": 0.9, "MENTIONS": 0.7, "APPEARS_IN": 0.5,
    "DEPENDS_ON": 0.85, "CONSTRAINS": 0.8, "REFINES": 0.8, "CONFLICTS_WITH": 0.8,
    "MEMBER_OF": 0.5, "HAS_PART": 0.75,
}
DEPENDENCY_EDGES = {"DEPENDS_ON", "CONSTRAINS", "REFINES", "CONFLICTS_WITH"}
LINEAGE_EDGES = {"DERIVED_FROM"} | DEPENDENCY_EDGES
ARTIFACT_LAYER = 4


def _h(text: str, n: int = 10) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:n]


def section_id(doc_id: str, path: list[str]) -> str:
    return f"SEC-{_h(doc_id + '|' + ' > '.join(path))}"


def add_edge(G: nx.MultiDiGraph, u: str, v: str, etype: str, **attrs: Any) -> bool:
    """Add a typed edge once; returns False if an edge of that type already exists."""
    if G.has_edge(u, v, key=etype):
        return False
    lu, lv = G.nodes[u].get("layer"), G.nodes[v].get("layer")
    G.add_edge(u, v, key=etype, type=etype, weight=attrs.pop("weight", EDGE_WEIGHTS[etype]),
               layer_relation="same" if lu == lv else "cross", **attrs)
    return True


def edges_of_type(G: nx.MultiDiGraph, node: str, etypes: set[str], *, out: bool = True):
    edges = G.out_edges(node, keys=True, data=True) if out else G.in_edges(node, keys=True, data=True)
    return sorted((e for e in edges if e[2] in etypes), key=lambda e: (e[2], e[0], e[1]))


def build_structure(manifest: Manifest, chunks: list[Chunk]) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph(schema_version=1, repo=manifest.repo, repo_revision=manifest.repo_revision,
                        source_authority=manifest.source_authority)
    docs = {d.doc_id: d for d in manifest.documents if d.status == "INGESTED"}
    for d in docs.values():
        G.add_node(d.doc_id, layer=3, type="document", title=d.path, path=d.path, kind=d.kind,
                   sha256=d.sha256, page_offsets=d.page_offsets, text_path=d.text_path, authority=d.authority)
    prev: dict[str, str] = {}
    for c in sorted(chunks, key=lambda c: (c.doc_id, c.char_start)):
        parent = c.doc_id
        for depth in range(len(c.section_path)):
            sid = section_id(c.doc_id, c.section_path[:depth + 1])
            if sid not in G:
                G.add_node(sid, layer=3, type="section", title=c.section_path[depth],
                           section_path=c.section_path[:depth + 1], doc_id=c.doc_id, summaries=[],
                           navigation_only=True)
                add_edge(G, sid, parent, "PART_OF")
            parent = sid
        G.add_node(c.chunk_id, layer=1, type="chunk", **c.model_dump(exclude={"chunk_id"}), summary="")
        add_edge(G, c.chunk_id, parent, "PART_OF")
        if c.doc_id in prev:
            add_edge(G, prev[c.doc_id], c.chunk_id, "NEXT")
        prev[c.doc_id] = c.chunk_id
    return G


def page_of(G: nx.MultiDiGraph, doc_id: str, offset: int) -> int:
    return bisect.bisect_right(G.nodes[doc_id]["page_offsets"], offset)


def save_graph(G: nx.MultiDiGraph, path: Path) -> None:
    data = nx.node_link_data(G, edges="edges")
    atomic_write_text(path, json.dumps(data, indent=1, default=str))


def load_graph(path: Path) -> nx.MultiDiGraph:
    data = json.loads(path.read_text(encoding="utf-8"))
    return nx.node_link_graph(data, directed=True, multigraph=True, edges="edges")


def _fact(G: nx.MultiDiGraph, rid: str, role: str, depth: int, via: list[dict]) -> dict:
    n = G.nodes[rid]
    return dict(req_id=rid, statement=n["statement"], quote=n["quote"], kind=n["kind"],
                status=n["status"], review_status=n["review_status"], role=role, depth=depth,
                via=via, chunk_id=n["chunk_id"], doc_path=n["doc_path"], page=n["page"],
                section=n["section"], trace_id=n.get("trace_id"), span_id=n.get("span_id"))


def lineage(G: nx.MultiDiGraph, node_id: str, max_depth: int = 4) -> dict:
    """Walk provenance edges from a node back to the requirements and source chunks behind it."""
    if node_id not in G:
        raise KeyError(node_id)
    facts: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    inferred_edges: list[dict] = []
    frontier: list[tuple[str, int, list[dict]]] = [(node_id, 0, [])]
    if G.nodes[node_id].get("type") == "requirement":
        facts[node_id] = _fact(G, node_id, "basis", 0, [])
    seen = {node_id}
    while frontier:
        node, depth, via = frontier.pop(0)
        if depth >= max_depth:
            continue
        for u, v, etype, data in edges_of_type(G, node, LINEAGE_EDGES):
            step = dict(src=u, type=etype, dst=v, status=data.get("status", "DOCUMENTED"))
            path = via + [step]
            if etype in DEPENDENCY_EDGES:
                inferred_edges.append(dict(step, rationale=data.get("rationale", ""),
                                           evidence_quote=data.get("evidence_quote", ""),
                                           review_status=data.get("review_status", "NOT_REVIEWED")))
            target = G.nodes[v]
            if target.get("type") == "requirement" and v not in facts:
                role = "basis" if all(s["type"] == "DERIVED_FROM" for s in path) else "dependency"
                facts[v] = _fact(G, v, role, depth + 1, path)
            elif target.get("type") == "chunk" and v not in sources:
                sources[v] = dict(chunk_id=v, doc_path=target["doc_path"],
                                  pages=[target["page_start"], target["page_end"]],
                                  section=" > ".join(target["section_path"]),
                                  text_sha256=target["text_sha256"])
            if v not in seen:
                seen.add(v)
                frontier.append((v, depth + 1, path))
    needs_review = any(f["review_status"] != "APPROVED" for f in facts.values()) or any(
        e["review_status"] != "APPROVED" for e in inferred_edges)
    return dict(node_id=node_id, facts=sorted(facts.values(), key=lambda f: (f["depth"], f["req_id"])),
                sources=sorted(sources.values(), key=lambda s: s["chunk_id"]),
                inferred_edges=inferred_edges,
                review_status="NEEDS_REVIEW" if needs_review else "APPROVED")


def attach_artifact(G: nx.MultiDiGraph, tracer: Tracer, artifact_id: str, kind: str,
                    parents: list[str], content: str | None = None,
                    metadata: dict | None = None) -> dict:
    """Register a generated artifact (e.g. an SVA) and log its full fact lineage to the trace."""
    missing = [p for p in parents if p not in G]
    if missing:
        raise KeyError(f"unknown parent nodes: {missing}")
    with tracer.span(f"lineage:{artifact_id}", as_type="chain",
                     input={"artifact_id": artifact_id, "kind": kind, "parents": parents}) as span:
        G.add_node(artifact_id, layer=ARTIFACT_LAYER, type=kind, content=content,
                   metadata=metadata or {}, trace_id=tracer.trace_id, span_id=span.id)
        for p in parents:
            add_edge(G, artifact_id, p, "DERIVED_FROM", status="DOCUMENTED")
        result = lineage(G, artifact_id)
        span.update(output={"facts": [{k: f[k] for k in ("req_id", "statement", "quote", "role",
                                                          "doc_path", "page", "section")}
                                      for f in result["facts"]],
                            "sources": result["sources"], "review_status": result["review_status"]},
                    metadata={"fact_ids": [f["req_id"] for f in result["facts"]],
                              "chunk_ids": [s["chunk_id"] for s in result["sources"]]})
    return result
