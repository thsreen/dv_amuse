"""Hybrid Graph-RAG retrieval: BM25 + dense seeds (convex fusion), Personalized PageRank, explained paths.

Evidence is always an L1 chunk. L2 requirements and L3 sections/communities contribute score by
propagation; each returned chunk reports its seed, component scores and the strongest graph path
from a seed to it.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass, field

import networkx as nx

STOPWORDS = set("a an and are as at be by for from has in is it its of on or that the this to was "
                "were will with when which while not no if then than".split())
GRAPH_LAYERS = (1, 2, 3)


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if t not in STOPWORDS]


def node_text(n: dict) -> str:
    t = n.get("type")
    if t == "chunk":
        return " ".join(n["section_path"]) + " " + n["text"]
    if t == "requirement":
        return n["statement"] + " " + n["quote"]
    if t == "entity":
        return " ".join([n["name"], *n["aliases"]])
    if t == "section":
        return n["title"] + " " + " ".join(n.get("summaries", []))
    if t == "community":
        return n["label"] + " " + n["summary"]
    return ""


@dataclass
class RetrievalConfig:
    seed_k: int = 12
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    dense_weight: float = 1.0
    lexical_weight: float = 1.0
    ppr_alpha: float = 0.5
    ppr_max_iter: int = 100
    ppr_tol: float = 1e-8
    ppr_weight: float = 0.3  # additive weight of graph propagation over normalized seed evidence
    top_k: int = 8
    max_per_section: int = 2
    section_penalty: float = 0.7
    edge_weights: dict[str, float] = field(default_factory=dict)


class BM25:
    def __init__(self, docs: dict[str, list[str]], k1: float, b: float):
        self.ids = sorted(docs)
        self.tf = {i: Counter(docs[i]) for i in self.ids}
        self.len = {i: len(docs[i]) for i in self.ids}
        self.avg = sum(self.len.values()) / max(1, len(self.ids))
        df = Counter(t for i in self.ids for t in self.tf[i])
        n = len(self.ids)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.k1, self.b = k1, b

    def score(self, query: list[str]) -> dict[str, float]:
        out = {}
        for i in self.ids:
            s = 0.0
            for t in set(query):
                f = self.tf[i].get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (
                        f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avg or 1)))
            if s > 0:
                out[i] = s
        return out


def fuse(rankings: list[tuple[float, dict[str, float]]]) -> dict[str, float]:
    """Convex combination of max-normalized score dictionaries (keeps score magnitude; cf. Bruch et al. 2022)."""
    total = sum(w for w, _ in rankings) or 1.0
    fused: dict[str, float] = {}
    for weight, scores in rankings:
        top = max(scores.values(), default=0.0) or 1.0
        for nid, s in scores.items():
            fused[nid] = fused.get(nid, 0.0) + (weight / total) * (s / top)
    return fused


def layered_view(G: nx.MultiDiGraph) -> nx.Graph:
    """Undirected view over graph layers with per-pair maximum edge weight (deterministic)."""
    H = nx.Graph()
    H.add_nodes_from(n for n, d in G.nodes(data=True) if d.get("layer") in GRAPH_LAYERS)
    for u, v, data in G.edges(data=True):
        if u in H and v in H:
            w = data["weight"]
            if H.has_edge(u, v):
                w = max(w, H.edges[u, v]["weight"])
            H.add_edge(u, v, weight=w, type=data["type"])
    return H


def _weighted_view(H: nx.Graph, overrides: dict[str, float]) -> nx.Graph:
    if not overrides:
        return H
    V = nx.Graph()
    V.add_nodes_from(H.nodes(data=True))
    for u, v, d in H.edges(data=True):
        V.add_edge(u, v, weight=overrides.get(d["type"], d["weight"]), type=d["type"])
    return V


def _label(G: nx.MultiDiGraph, nid: str) -> str:
    n = G.nodes[nid]
    t = n.get("type")
    name = {"chunk": lambda: n["section_title"], "requirement": lambda: n["statement"][:60],
            "entity": lambda: n["name"], "section": lambda: n["title"],
            "community": lambda: n["label"], "document": lambda: n["title"]}.get(t, lambda: "")()
    return f"{t}:{nid} '{name}'"


def _evidence_chunk(G: nx.MultiDiGraph, nid: str) -> str | None:
    n = G.nodes[nid]
    if n.get("type") == "chunk":
        return nid
    if n.get("type") == "requirement":
        return n["chunk_id"]
    return None


def retrieve(G: nx.MultiDiGraph, query: str, cfg: RetrievalConfig | None = None, *,
             dense: dict[str, float] | None = None, extra_seeds: dict[str, float] | None = None,
             H: nx.Graph | None = None) -> dict:
    cfg = cfg or RetrievalConfig()
    docs = {nid: tokenize(node_text(n)) for nid, n in G.nodes(data=True) if n.get("layer") in GRAPH_LAYERS}
    docs = {k: v for k, v in docs.items() if v}
    q = tokenize(query)
    lexical = BM25(docs, cfg.bm25_k1, cfg.bm25_b).score(q) if docs and q else {}
    rankings = [(cfg.lexical_weight, lexical)]
    if dense:
        rankings.append((cfg.dense_weight, dense))
    base = _weighted_view(H if H is not None else layered_view(G), cfg.edge_weights)
    fused = fuse(rankings) if lexical or dense else {}
    fused = {k: v for k, v in fused.items() if k in base}
    seeds = dict(sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:cfg.seed_k])
    for nid, w in (extra_seeds or {}).items():
        if nid in base:
            seeds[nid] = seeds.get(nid, 0.0) + w
    if not seeds:
        return dict(query=query, seeds=[], evidence=[], requirements=[])

    total = sum(seeds.values())
    personalization = {n: w / total for n, w in seeds.items()}
    ppr = nx.pagerank(base, alpha=cfg.ppr_alpha, personalization=personalization,
                      max_iter=cfg.ppr_max_iter, tol=cfg.ppr_tol, weight="weight")

    # Shortest-cost paths (cost = -log weight) from the nearest seed explain each chunk.
    _, paths = nx.multi_source_dijkstra(
        base, sources=list(seeds), weight=lambda u, v, d: -math.log(max(d["weight"], 1e-9)))

    per_chunk: dict[str, float] = {}
    for nid, score in ppr.items():
        cid = _evidence_chunk(G, nid) if score > 0 else None
        if cid:
            per_chunk[cid] = per_chunk.get(cid, 0.0) + score
    top_ppr = max(per_chunk.values(), default=1.0) or 1.0
    top_fused = max(fused.values(), default=1.0) or 1.0
    ranked = []
    # A chunk is a candidate only if a seed path reaches it; unreachable chunks have no explanation.
    for cid in sorted(c for c in set(per_chunk) | set(fused)
                      if G.nodes[c].get("type") == "chunk" and c in paths):
        score = fused.get(cid, 0.0) / top_fused + cfg.ppr_weight * per_chunk.get(cid, 0.0) / top_ppr
        ranked.append([score, cid])
    ranked.sort(key=lambda r: (-r[0], r[1]))
    section_count: Counter = Counter()
    for r in ranked:
        sec = " > ".join(G.nodes[r[1]]["section_path"])
        if section_count[sec] >= cfg.max_per_section:
            r[0] *= cfg.section_penalty
        section_count[sec] += 1
    ranked.sort(key=lambda r: (-r[0], r[1]))

    evidence = []
    for score, cid in ranked[:cfg.top_k]:
        n = G.nodes[cid]
        path = _describe_path(base, paths[cid], seeds, lexical, dense)
        evidence.append(dict(
            chunk_id=cid, score=round(score, 4), doc_path=n["doc_path"],
            pages=[n["page_start"], n["page_end"]], section=" > ".join(n["section_path"]),
            text=n["text"], components=dict(
                lexical=round(lexical.get(cid, 0.0), 4), dense=round((dense or {}).get(cid, 0.0), 4),
                fused_normalized=round(fused.get(cid, 0.0) / top_fused, 4),
                ppr_normalized=round(per_chunk.get(cid, 0.0) / top_ppr, 4)),
            supporting_requirements=sorted({
                r for r, _, _ in G.in_edges(cid, keys=True)
                if G.nodes[r].get("type") == "requirement" and ppr.get(r, 0.0) > 0})[:cfg.top_k],
            path=path, explanation=_explain(G, path, score)))
    reqs = sorted(((ppr[n], n) for n in ppr if G.nodes[n].get("type") == "requirement"),
                  key=lambda x: (-x[0], x[1]))
    return dict(query=query, seeds=[dict(node=n, fused=round(s, 5)) for n, s in seeds.items()],
                evidence=evidence,
                requirements=[dict(req_id=nid, ppr=round(s, 6), statement=G.nodes[nid]["statement"])
                              for s, nid in reqs[:cfg.top_k]])


def _describe_path(base: nx.Graph, nodes: list[str], seeds: dict, lexical: dict, dense) -> list[dict]:
    seed = nodes[0]
    steps = [dict(seed=seed, fused=round(seeds.get(seed, 0.0), 5), lexical=round(lexical.get(seed, 0.0), 3),
                  dense=round((dense or {}).get(seed, 0.0), 3))]
    for a, b in zip(nodes, nodes[1:]):
        d = base.edges[a, b]
        steps.append(dict(edge=d["type"], weight=round(d["weight"], 3), frm=a, to=b))
    return steps


def _explain(G: nx.MultiDiGraph, path: list[dict], final: float) -> str:
    seed = path[0]
    parts = [f"seed {_label(G, seed['seed'])} fused={seed['fused']} lex={seed['lexical']} dense={seed['dense']}"]
    for step in path[1:]:
        parts.append(f"{step['edge']} x{step['weight']} -> {_label(G, step['to'])}")
    return " | ".join(parts) + f" => score {final:.3f}"
