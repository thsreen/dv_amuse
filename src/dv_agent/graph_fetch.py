"""Graph processing and fetching beyond seed retrieval.

- Owner edges: entities the model recorded with a parent (register -> field, interface -> signal) get a
  HAS_PART edge, so the entity hierarchy can be walked.
- Entity-centred fetch: names in a query resolve to graph entities; typed traversal gathers their parts,
  owners, the requirements that mention them, dependency preconditions, chunks, sections and communities.
- Dependency closure and ordering: bounded multi-hop preconditions, cycles, a deterministic
  precondition-first order, and conflicts.
- Global fetch: communities ranked by their summaries, expanded into requirements and chunks.
- Requirement coverage: which requirements a set of citations does and does not cover.

Every fetched item records how it was reached ("via"), and only specification-derived nodes are used.
"""
import re

import networkx as nx

from .extract import _alias_index, _name_keys, normalize_name
from .graph import add_edge, edges_of_type
from .retrieval import BM25, node_text, tokenize

OWNER_EDGE = "HAS_PART"
PRECONDITION_EDGES = {"DEPENDS_ON", "CONSTRAINS", "REFINES"}
ORDER_EDGES = {"DEPENDS_ON"}
DEPTH_DECAY = 0.85
MAX_CYCLES = 20


def _is(G: nx.MultiDiGraph, nid: str, kind: str) -> bool:
    return G.nodes[nid].get("type") == kind


def add_owner_edges(G: nx.MultiDiGraph) -> dict:
    """HAS_PART edges from each owner entity to the entities that name it as parent."""
    index = _alias_index(G)
    linked, unresolved = 0, []
    for eid, d in sorted(G.nodes(data=True)):
        if d.get("type") != "entity" or not d.get("parent"):
            continue
        owner = next((index[k] for k in _name_keys(d["parent"], []) if index.get(k) not in (None, eid)), None)
        if owner is None:
            unresolved.append(dict(entity=eid, parent=d["parent"]))
            continue
        linked += add_edge(G, owner, eid, OWNER_EDGE, status="INFERRED")
    return dict(owner_edges=linked, unresolved_parents=unresolved)


def _word(text: str, key: str) -> bool:
    return re.search(rf"(?<![a-z0-9_]){re.escape(key)}(?![a-z0-9_])", text) is not None


def resolve_entities(G: nx.MultiDiGraph, text: str, max_anchors: int = 8) -> list[dict]:
    """Entities named in the text. An owned entity (a field) matches only if its owner is also named."""
    ctx = normalize_name(text)
    found = []
    for eid, d in sorted(G.nodes(data=True)):
        if d.get("type") != "entity":
            continue
        hit = next((k for k in sorted(_name_keys(d["name"], d["aliases"]), key=len, reverse=True)
                    if len(k) >= 2 and _word(ctx, k)), None)
        if hit is None:
            continue
        if d.get("parent") and not any(_word(ctx, k) for k in _name_keys(d["parent"], [])):
            continue
        found.append(dict(entity_id=eid, name=d["name"], matched=hit))
    found.sort(key=lambda f: (-len(f["matched"]), f["entity_id"]))
    return found[:max_anchors]


def dependency_closure(G: nx.MultiDiGraph, roots: list[str], max_depth: int = 4,
                       edge_types: set[str] = PRECONDITION_EDGES) -> list[dict]:
    """Requirements the roots depend on, transitively (shallowest path kept), excluding the roots."""
    best: dict[str, dict] = {}
    frontier = [(r, 0, []) for r in sorted(set(roots)) if r in G]
    while frontier:
        node, depth, path = frontier.pop(0)
        if depth >= max_depth:
            continue
        for u, v, etype, _ in edges_of_type(G, node, edge_types):
            if v in roots or not _is(G, v, "requirement"):
                continue
            step = path + [dict(src=u, type=etype, dst=v)]
            if v not in best or len(step) < best[v]["depth"]:
                best[v] = dict(req_id=v, depth=len(step), root=step[0]["src"], path=step)
                frontier.append((v, depth + 1, step))
    return sorted(best.values(), key=lambda x: (x["depth"], x["req_id"]))


def dependency_order(G: nx.MultiDiGraph, req_ids: list[str], max_depth: int = 4) -> dict:
    """Precondition-first order over the requirements and their closure; cycles and conflicts reported."""
    nodes = set(r for r in req_ids if r in G) | {c["req_id"] for c in dependency_closure(G, req_ids, max_depth)}
    D = nx.DiGraph()
    D.add_nodes_from(sorted(nodes))
    conflicts = []
    for n in sorted(nodes):
        for u, v, etype, data in edges_of_type(G, n, ORDER_EDGES | {"CONFLICTS_WITH"}):
            if v not in nodes:
                continue
            if etype == "CONFLICTS_WITH":
                conflicts.append(dict(src=u, dst=v, rationale=data.get("rationale", "")))
            else:
                D.add_edge(v, u)  # the precondition comes first
    cycles = []
    for cyc in nx.simple_cycles(D, length_bound=6):
        cycles.append(sorted(cyc))
        if len(cycles) >= MAX_CYCLES:
            break
    C = nx.condensation(D)
    members = {c: sorted(C.nodes[c]["members"]) for c in C.nodes}
    order = [r for c in nx.lexicographical_topological_sort(C, key=lambda c: members[c][0]) for r in members[c]]
    return dict(order=order, cycles=sorted(cycles), conflicts=conflicts,
                edges=[dict(precondition=u, dependent=v) for u, v in sorted(D.edges)])


def entity_context(G: nx.MultiDiGraph, anchors: list[str], hops: int = 2, max_requirements: int = 30) -> dict:
    """Typed traversal from anchor entities: parts, owners, mentioning requirements, preconditions, chunks."""
    anchors = [a for a in anchors if a in G and _is(G, a, "entity")]
    req_score: dict[str, float] = {}
    req_via: dict[str, str] = {}

    def credit(rid: str, score: float, via: str) -> None:
        if score > req_score.get(rid, 0.0):
            req_score[rid], req_via[rid] = score, via

    parts, owners = {}, {}
    for a in anchors:
        for _, child, _, _ in edges_of_type(G, a, {OWNER_EDGE}):
            parts.setdefault(child, a)
        for owner, _, _, _ in edges_of_type(G, a, {OWNER_EDGE}, out=False):
            owners.setdefault(owner, a)
    tiers = ([(a, 1.0, "mentions {}") for a in anchors] + [(p, 0.8, "mentions part {}") for p in parts]
             + [(o, 0.6, "mentions owner {}") for o in owners])
    for ent, score, how in tiers:
        for r, _, _, _ in edges_of_type(G, ent, {"MENTIONS"}, out=False):
            if _is(G, r, "requirement"):
                credit(r, score, how.format(G.nodes[ent]["name"]))
    for c in dependency_closure(G, list(req_score), max_depth=hops):
        credit(c["req_id"], req_score[c["root"]] * DEPTH_DECAY ** c["depth"],
               f"precondition (depth {c['depth']}) of {c['root']}")
    ranked = sorted(req_score, key=lambda r: (-req_score[r], r))[:max_requirements]
    chunk_score: dict[str, tuple[float, str]] = {}
    for r in ranked:
        cid = G.nodes[r]["chunk_id"]
        if req_score[r] > chunk_score.get(cid, (0.0, ""))[0]:
            chunk_score[cid] = (req_score[r], f"source of {r}")
    for ent in anchors + list(parts):
        for _, cid, _, _ in edges_of_type(G, ent, {"APPEARS_IN"}):
            if cid not in chunk_score:
                chunk_score[cid] = (0.5, f"{G.nodes[ent]['name']} appears here")
    communities = sorted({c for n in anchors + ranked for _, c, _, _ in edges_of_type(G, n, {"MEMBER_OF"})})
    return dict(
        anchors=[dict(entity_id=a, name=G.nodes[a]["name"], kind=G.nodes[a]["kind"]) for a in anchors],
        parts=[dict(entity_id=p, name=G.nodes[p]["name"], owner=G.nodes[parts[p]]["name"]) for p in sorted(parts)],
        owners=[dict(entity_id=o, name=G.nodes[o]["name"]) for o in sorted(owners)],
        requirements=[dict(req_id=r, score=round(req_score[r], 4), via=req_via[r]) for r in ranked],
        chunks=[dict(chunk_id=c, score=round(s, 4), via=v)
                for c, (s, v) in sorted(chunk_score.items(), key=lambda kv: (-kv[1][0], kv[0]))],
        communities=communities)


def global_fetch(G: nx.MultiDiGraph, query: str, top: int = 3, max_requirements: int = 20) -> dict:
    """Communities ranked by their summaries (largest first when nothing matches), expanded to requirements."""
    coms = [n for n, d in G.nodes(data=True) if d.get("type") == "community"]
    if not coms:
        return dict(communities=[], requirements=[], chunks=[])
    scores = BM25({c: tokenize(node_text(G.nodes[c])) for c in coms}, 1.5, 0.75).score(tokenize(query))
    ranked = sorted(coms, key=lambda c: (-scores.get(c, 0.0), -len(G.nodes[c]["members"]), c))[:top]
    top_score = max([scores.get(c, 0.0) for c in ranked] + [0.0]) or 1.0
    req_score: dict[str, tuple[float, str]] = {}
    for c in ranked:
        weight = scores.get(c, 0.0) / top_score if scores else 0.5
        weight = weight or 0.5
        for m in G.nodes[c]["members"]:
            if _is(G, m, "requirement"):
                cand = (weight, f"member of community {G.nodes[c]['label']}")
            elif _is(G, m, "entity"):
                for r, _, _, _ in edges_of_type(G, m, {"MENTIONS"}, out=False):
                    if _is(G, r, "requirement") and 0.7 * weight > req_score.get(r, (0.0, ""))[0]:
                        req_score[r] = (0.7 * weight, f"mentions {G.nodes[m]['name']} (community {G.nodes[c]['label']})")
                continue
            else:
                continue
            if cand[0] > req_score.get(m, (0.0, ""))[0]:
                req_score[m] = cand
    reqs = sorted(req_score, key=lambda r: (-req_score[r][0], r))[:max_requirements]
    chunks: dict[str, tuple[float, str]] = {}
    for r in reqs:
        cid = G.nodes[r]["chunk_id"]
        if req_score[r][0] > chunks.get(cid, (0.0, ""))[0]:
            chunks[cid] = (req_score[r][0], f"source of {r}")
    return dict(
        communities=[dict(community_id=c, label=G.nodes[c]["label"], summary=G.nodes[c]["summary"],
                          score=round(scores.get(c, 0.0), 4), navigation_only=True) for c in ranked],
        requirements=[dict(req_id=r, score=round(req_score[r][0], 4), via=req_score[r][1]) for r in reqs],
        chunks=[dict(chunk_id=c, score=round(s, 4), via=v)
                for c, (s, v) in sorted(chunks.items(), key=lambda kv: (-kv[1][0], kv[0]))])


def requirement_coverage(G: nx.MultiDiGraph, cited_req_ids: set[str], cited_chunk_ids: set[str]) -> dict:
    """Requirements cited directly, only through their chunk, or not at all (document order)."""
    reqs = sorted((n for n, d in G.nodes(data=True) if d.get("type") == "requirement"),
                  key=lambda r: (G.nodes[r]["doc_id"], G.nodes[r]["quote_start"], r))
    covered = [r for r in reqs if r in cited_req_ids]
    chunk_only = [r for r in reqs if r not in cited_req_ids and G.nodes[r]["chunk_id"] in cited_chunk_ids]
    uncovered = [r for r in reqs if r not in cited_req_ids and G.nodes[r]["chunk_id"] not in cited_chunk_ids]

    def rec(r):
        n = G.nodes[r]
        return dict(req_id=r, statement=n["statement"], section=n["section"], page=n["page"], kind=n["kind"])
    return dict(total=len(reqs), covered=len(covered), chunk_only=[rec(r) for r in chunk_only],
                uncovered=[rec(r) for r in uncovered],
                ratio=round(len(covered) / len(reqs), 4) if reqs else None)
