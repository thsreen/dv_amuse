"""Explainable RTL Graph-RAG: hybrid seeds, PageRank and bounded typed context sources."""
import hashlib
import math
import re
from collections import Counter, deque
from dataclasses import dataclass

import networkx as nx

from .graph import FLOW_EDGES
from .source import RTLExtractionError

SOURCES = ("retrieval", "entity", "upstream", "downstream", "domain", "community")
STOP = set("a an and are as at be by for from has how in is it of on or that the this to what when which with working".split())
SYNONYMS = {"clocked": "clock", "clocks": "clock", "reset_by": "reset", "reset": "reset",
            "clocked_by": "clock", "modules": "module", "connected": "connection", "connections": "connection"}


@dataclass
class QueryConfig:
    top_k: int = 16
    seed_k: int = 12
    hops: int = 3
    max_expansions: int = 256
    max_edges: int = 48
    max_excerpts: int = 16
    max_chars: int = 24_000
    ppr_alpha: float = .65
    ppr_weight: float = .35
    dense_weight: float = .5

    def __post_init__(self):
        for key in ("top_k", "seed_k", "hops", "max_expansions", "max_edges", "max_excerpts", "max_chars"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise RTLExtractionError(f"query budget {key} must be a positive integer")
        if self.top_k > 100 or self.hops > 8 or self.max_expansions > 4096:
            raise RTLExtractionError("query node/hop budgets exceed supported limits")
        if not 0 < self.ppr_alpha < 1 or not 0 <= self.ppr_weight <= 1 or not 0 <= self.dense_weight <= 1:
            raise RTLExtractionError("query weights must be in [0,1] and PageRank alpha in (0,1)")


def terms(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9_$]+", text.lower())
    words += [part for word in words if "_" in word for part in word.split("_") if part]
    return [SYNONYMS.get(w, w) for w in words if w not in STOP]


def bm25(documents: dict[str, str], query: str) -> dict[str, float]:
    bags = {n: Counter(terms(text)) for n, text in documents.items()}
    lengths = {n: sum(bag.values()) for n, bag in bags.items()}
    average = sum(lengths.values()) / max(1, len(lengths)) or 1
    frequencies = Counter(term for bag in bags.values() for term in bag)
    scores = {}
    for n, bag in bags.items():
        score = 0.0
        for term in set(terms(query)):
            frequency = bag[term]
            if frequency:
                idf = math.log(1 + (len(bags) - frequencies[term] + .5) / (frequencies[term] + .5))
                score += idf * frequency * 2.5 / (frequency + 1.5 * (.25 + .75 * lengths[n] / average))
        if score:
            scores[n] = score
    return scores


def node_text(G: nx.MultiDiGraph, n: str) -> str:
    d = G.nodes[n]
    text = " ".join(str(d.get(k, "")) for k in ("label", "name", "description", "expression", "summary",
                                                 "type", "module_type", "process_kind", "sensitivity"))
    relationships = []
    for _, v, k in sorted(G.out_edges(n, keys=True)):
        if k in ("CLOCKED_BY", "RESET_BY", "PORT_DEPENDS_ON", "CONTROL_DEPENDS_ON", "DATA_DEPENDS_ON"):
            relationships.append(k + " " + G.nodes[v]["label"])
    # Source comments help navigation; every returned claim still cites an exact excerpt.
    excerpts = [G.nodes[c]["text"] for c in d.get("evidence", [])[:2] if c in G]
    return text + " " + " ".join(relationships) + " " + " ".join(excerpts)[:1600]


def view(G: nx.MultiDiGraph, scope: str) -> nx.Graph:
    if scope and not any(d.get("scope") == scope for _, d in G.nodes(data=True)):
        raise RTLExtractionError(f"unknown RTL scope: {scope}")
    allowed = {n for n, d in G.nodes(data=True) if d.get("layer") == 2 and
               (not scope or d.get("scope") == scope or d.get("scope", "").startswith(scope + "."))}
    if scope:
        allowed |= {v for u in list(allowed) for _, v, k in G.out_edges(u, keys=True) if k == "INSTANCE_OF"}
        allowed |= {u for u, v, k in G.edges(keys=True) if k == "FEATURE_MEMBER" and v in allowed}
    allowed |= {n for n, d in G.nodes(data=True) if d.get("type") == "community"
                and any(m in allowed for m in d["members"])}
    H = nx.Graph()
    H.add_nodes_from(sorted(allowed))
    for u, v, k, d in sorted(G.edges(keys=True, data=True)):
        if u in H and v in H:
            if not H.has_edge(u, v) or H[u][v]["weight"] < d["weight"]:
                H.add_edge(u, v, weight=d["weight"], type=k)
    return H


def anchors(G: nx.MultiDiGraph, H: nx.Graph, query: str, limit: int) -> list[str]:
    found = []
    for n in H:
        d = G.nodes[n]
        if d.get("type") not in ("instance", "signal", "feature", "module"):
            continue
        for name in (d["label"], d.get("name", "")):
            if name and re.search(r"(?<![\w.$])" + re.escape(name) + r"(?![\w.$])", query, re.I):
                found.append((len(name), n))
                break
    return [n for _, n in sorted(found, key=lambda p: (-p[0], p[1]))[:limit]]


def traverse(G: nx.MultiDiGraph, H: nx.Graph, starts: list[str], hops: int, budget: int,
             *, kinds: set[str] | None = None, backwards: bool = False) -> dict[str, list[str]]:
    paths = {n: [n] for n in starts if n in H}
    queue = deque(paths)
    while queue and len(paths) < budget:
        u = queue.popleft()
        if len(paths[u]) - 1 >= hops:
            continue
        if kinds is None:
            candidates = sorted(H.neighbors(u), key=lambda v: (-H[u][v]["weight"], v))
        else:
            edges = G.in_edges(u, keys=True) if backwards else G.out_edges(u, keys=True)
            candidates = sorted({a if backwards else b for a, b, k in edges if k in kinds})
        for v in candidates:
            if v in H and v not in paths:
                paths[v] = paths[u] + [v]
                queue.append(v)
                if len(paths) >= budget:
                    break
    return paths


def verified_excerpt(G: nx.MultiDiGraph, cid: str) -> dict | None:
    if cid not in G or G.nodes[cid].get("type") != "excerpt":
        return None
    d = G.nodes[cid]
    text = d["text"]
    if hashlib.sha256(text.encode()).hexdigest() != d["text_sha256"] or d["char_end"] - d["char_start"] != len(text):
        return None
    return dict(id=cid, **{k: d[k] for k in ("path", "line_start", "line_end", "char_start", "char_end",
                                            "text", "text_sha256", "file_sha256")})


def fetch_context(G: nx.MultiDiGraph, query: str, *, scope: str = "", cfg: QueryConfig | None = None,
                  dense: dict[str, float] | None = None) -> dict:
    """Rank an evidence bundle for a later model; no specification-flow imports or API calls."""
    cfg = cfg or QueryConfig()
    H = view(G, scope)
    documents = {}
    for n in H:
        if G.nodes[n]["type"] == "community" and scope:
            documents[n] = " ".join(G.nodes[m]["label"] for m in G.nodes[n]["members"] if m in H)
        else:
            documents[n] = node_text(G, n)
    lexical = bm25(documents, query)
    exact = anchors(G, H, query, cfg.seed_k)
    if dense and any(not math.isfinite(v) for v in dense.values()):
        raise RTLExtractionError("dense scores must be finite")
    dense = {n: max(0., v) for n, v in (dense or {}).items() if n in H and v > 0}
    maxlex, maxdense = max(lexical.values(), default=1), max(dense.values(), default=1)
    fused = {n: lexical.get(n, 0) / maxlex * (1 - cfg.dense_weight if dense else 1)
             + dense.get(n, 0) / maxdense * cfg.dense_weight for n in set(lexical) | set(dense)}
    seeds = dict(sorted(fused.items(), key=lambda p: (-p[1], p[0]))[:cfg.seed_k])
    for n in exact:
        seeds[n] = seeds.get(n, 0) + 2
    result = dict(query=query, scope=scope, seeds=[], nodes=[], facts=[], evidence=[], paths=[],
                  navigation=[], domains=[], diagnostics=G.graph.get("diagnostics", []),
                  retrieval=dict(sources={s: 0 for s in SOURCES}, dense="PASS" if dense else "NOT_RUN"),
                  limitations=["Static whole-signal dependencies are conservative; no behavioral proof or timing/CDC sign-off.",
                               "Clock/reset roles from leading constant-assignment patterns are inferences."])
    if not seeds:
        return result
    total = sum(seeds.values())
    try:
        ppr = nx.pagerank(H, alpha=cfg.ppr_alpha, personalization={n: w / total for n, w in seeds.items()},
                          max_iter=100, tol=1e-8, weight="weight")
        result["retrieval"]["pagerank"] = "PASS"
    except nx.PowerIterationFailedConvergence:
        ppr = {}
        result["retrieval"]["pagerank"] = "NOT_CONVERGED"
    maxppr = max(ppr.values(), default=1)
    score = {n: fused.get(n, 0) + cfg.ppr_weight * ppr.get(n, 0) / maxppr + (1 if n in exact else 0) for n in H}
    ranked = sorted(H, key=lambda n: (-score[n], n))
    # Hop-bounded BFS keeps an available short path, unlike filtering an unconstrained weighted path.
    explained = traverse(G, H, exact or list(seeds), cfg.hops, cfg.max_expansions)
    context_view = H.subgraph(explained)
    candidates = {s: [] for s in SOURCES}
    via: dict[tuple[str, str], list[str]] = {}
    domain_roles: dict[str, set[str]] = {}

    def add(source: str, n: str, path: list[str]):
        if n in explained and n not in candidates[source]:
            candidates[source].append(n)
            via[source, n] = path

    for n in ranked:
        if n in explained and G.nodes[n].get("layer") == 2:
            add("retrieval", n, explained[n])
    neighborhood = traverse(G, context_view, exact or list(seeds)[:4], min(2, cfg.hops), cfg.max_expansions)
    for n, path in neighborhood.items():
        if G.nodes[n].get("layer") == 2:
            add("entity", n, path)
    flow_starts = [n for n in (exact or ranked[:4]) if G.nodes[n]["type"] == "signal"]
    if not flow_starts:
        flow_starts = [n for n in neighborhood if G.nodes[n]["type"] == "signal"][:16]
    for source, backwards in (("upstream", False), ("downstream", True)):
        for n, path in traverse(G, context_view, flow_starts, cfg.hops, cfg.max_expansions,
                                kinds=FLOW_EDGES, backwards=backwards).items():
            if len(path) > 1:
                add(source, n, path)
    for n in list(neighborhood)[:32]:
        for _, signal, kind, d in sorted(G.out_edges(n, keys=True, data=True)):
            if kind in ("CLOCKED_BY", "RESET_BY") and signal in H:
                add("domain", signal, neighborhood[n] + [signal])
                domain_roles.setdefault(signal, set()).add(kind)
                root = d.get("root_signal", signal)
                if root in H and root in explained:
                    add("domain", root, explained[root])
                    domain_roles.setdefault(root, set()).add(kind)
    for domain in G.graph.get("domains", []):
        if domain["signal"] in exact:
            for n in (domain["clocked"] + domain["reset"])[:32]:
                if n in explained:
                    add("domain", n, explained[n])
    community_nodes = [n for n in ranked if G.nodes[n]["type"] == "community" and n in explained][:2]
    for community in community_nodes:
        members = [n for n in G.nodes[community]["members"] if n in H]
        for n in sorted(members, key=lambda n: (-score[n], n))[:12]:
            path = explained[community] + [n]
            if len(path) - 1 <= cfg.hops:
                add("community", n, path)
        result["navigation"].append(dict(id=community, summary="; ".join(G.nodes[n]["label"] for n in members[:16]),
                                          navigation_only=True))
    preferred_domains = []
    for role in ("CLOCKED_BY", "RESET_BY"):
        match = next((n for n in candidates["domain"] if role in domain_roles.get(n, set())), None)
        if match and match not in preferred_domains:
            preferred_domains.append(match)
    candidates["domain"] = preferred_domains + [n for n in candidates["domain"] if n not in preferred_domains]
    # Reserve a clock/reset pair and one slot per other source, then fill by rank.
    chosen = []
    for source in SOURCES:
        quota = 2 if source == "domain" else 1
        added = 0
        for n in candidates[source]:
            if n not in chosen and len(chosen) < cfg.top_k:
                chosen.append(n)
                added += 1
                if added >= quota:
                    break
    pool = {n for nodes in candidates.values() for n in nodes}
    for n in sorted(pool, key=lambda n: (-score[n], n)):
        if n not in chosen and len(chosen) < cfg.top_k:
            chosen.append(n)
    evidence_ids = []
    for n in chosen:
        evidence_ids += G.nodes[n].get("evidence", [])[:2]
    facts = []
    eligible = [(u, v, k, d) for u, v, k, d in G.edges(keys=True, data=True)
                if u in chosen and v in chosen and k not in ("DERIVED_FROM", "MEMBER_OF", "CONTAINS", "INSTANCE_OF")]
    eligible.sort(key=lambda e: (e[0] not in exact and e[1] not in exact,
                                  e[2] not in ("CLOCKED_BY", "RESET_BY"),
                                  -score[e[0]] - score[e[1]], e[0], e[1], e[2]))
    for u, v, kind, d in eligible:
        facts.append(dict(source=u, source_label=G.nodes[u]["label"], target=v,
                          target_label=G.nodes[v]["label"], relation=kind,
                          **{k: value for k, value in d.items() if k not in ("type", "weight")}))
        if len(facts) >= cfg.max_edges:
            break
    # Relations get first choice of citations so a statement cannot cite an unrelated shared file.
    evidence_ids = [c for f in facts for c in f["evidence"]] + evidence_ids
    evidence, chars, rejected = {}, 0, []
    for cid in dict.fromkeys(evidence_ids):
        excerpt = verified_excerpt(G, cid)
        if excerpt is None:
            rejected.append(cid)
            continue
        if len(evidence) < cfg.max_excerpts and chars + len(excerpt["text"]) <= cfg.max_chars:
            evidence[cid] = excerpt
            chars += len(excerpt["text"])
    result["facts"] = [dict(f, evidence=[c for c in f["evidence"] if c in evidence]) for f in facts
                       if any(c in evidence for c in f["evidence"])]
    for n in chosen:
        node = G.nodes[n]
        sources = [s for s in SOURCES if n in candidates[s]]
        primary = sources[0]
        path = via[primary, n]
        record = {k: v for k, v in node.items() if k not in ("evidence", "text", "members")}
        result["nodes"].append(dict(id=n, **record, score=round(score[n], 6), sources=sources,
                                    evidence=[c for c in node.get("evidence", []) if c in evidence],
                                    citation_status="VERIFIED" if any(c in evidence for c in node.get("evidence", [])) else "NOT_INCLUDED",
                                    components=dict(lexical=round(lexical.get(n, 0), 6),
                                                    dense=round(dense.get(n, 0), 6), ppr=round(ppr.get(n, 0), 6))))
        steps = []
        for u, v in zip(path, path[1:]):
            edges = ([(u, v, k) for k in G.get_edge_data(u, v, default={})]
                     + [(v, u, k) for k in G.get_edge_data(v, u, default={})])
            # Retain direction in explanations even though ranking uses an undirected navigation view.
            steps.append([dict(source=a, relation=k, target=b) for a, b, k in edges])
        result["paths"].append(dict(target=n, source=primary, nodes=path, steps=steps))
    selected = set(chosen)
    result["domains"] = [dict(signal=d["signal"], clocked=[n for n in d["clocked"] if n in selected],
                               reset=[n for n in d["reset"] if n in selected]) for d in G.graph.get("domains", [])
                         if d["signal"] in selected or selected.intersection(d["clocked"] + d["reset"])]
    result["evidence"] = list(evidence.values())
    result["seeds"] = [dict(id=n, score=round(w, 6)) for n, w in sorted(seeds.items(), key=lambda p: (-p[1], p[0]))]
    result["retrieval"].update(sources={s: sum(s in n["sources"] for n in result["nodes"]) for s in SOURCES},
                                expansions=len(explained), rejected_excerpts=rejected, evidence_chars=chars,
                                omitted_facts=len(facts) - len(result["facts"]), budgets=vars(cfg))
    if scope:
        result["diagnostics"] = [d for d in result["diagnostics"] if d["scope"] == scope or d["scope"].startswith(scope + ".")]
    return result
