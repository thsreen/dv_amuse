"""L3 knowledge building: deterministic communities over L2 entities and requirements.

Community detection is greedy modularity (deterministic for a fixed graph). Each community gets an
extractive summary built from its member statements; summaries are navigation aids, never evidence.
"""
import hashlib

import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities

from .graph import EDGE_WEIGHTS, add_edge

SUMMARY_CHARS = 700
MIN_MEMBERS = 2


def _layer2_view(G: nx.MultiDiGraph) -> nx.Graph:
    H = nx.Graph()
    members = [n for n, d in G.nodes(data=True) if d.get("type") in ("requirement", "entity")]
    H.add_nodes_from(members)
    for u, v, data in G.edges(data=True):
        if u in H and v in H:
            w = data["weight"]
            if H.has_edge(u, v):
                w = max(w, H.edges[u, v]["weight"])
            H.add_edge(u, v, weight=w)
    return H


def build_communities(G: nx.MultiDiGraph) -> dict:
    H = _layer2_view(G)
    H.remove_nodes_from([n for n in list(H.nodes) if H.degree(n) == 0])
    if H.number_of_edges() == 0:
        return dict(communities=0)
    groups = greedy_modularity_communities(H, weight="weight")
    created = 0
    for group in sorted((sorted(g) for g in groups), key=lambda g: (-len(g), g[0])):
        if len(group) < MIN_MEMBERS:
            continue
        ents = sorted((m for m in group if G.nodes[m]["type"] == "entity"),
                      key=lambda m: (-H.degree(m), G.nodes[m]["name"]))
        reqs = sorted((m for m in group if G.nodes[m]["type"] == "requirement"),
                      key=lambda m: (G.nodes[m]["doc_id"], G.nodes[m]["quote_start"]))
        label = ", ".join(G.nodes[e]["name"] for e in ents[:3]) or "requirements"
        summary = " ".join(G.nodes[r]["statement"] for r in reqs)[:SUMMARY_CHARS]
        cid = f"COM-{_stable(group)}"
        G.add_node(cid, layer=3, type="community", label=label, summary=summary, members=group,
                   navigation_only=True)
        for m in group:
            add_edge(G, m, cid, "MEMBER_OF", weight=EDGE_WEIGHTS["MEMBER_OF"])
        created += 1
    return dict(communities=created, layer2_nodes=H.number_of_nodes(), layer2_edges=H.number_of_edges())


def _stable(members: list[str]) -> str:
    return hashlib.sha256("|".join(sorted(members)).encode()).hexdigest()[:10]
