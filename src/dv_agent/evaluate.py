"""Labeled-set retrieval evaluation: recall@k and mean reciprocal rank.

A case lists substrings of the section paths that count as relevant. Metrics are deterministic
given the graph, the query set and the embedder.
"""
import json
from dataclasses import dataclass, replace
from pathlib import Path

import networkx as nx

from .dense import Embedder, dense_scores
from .retrieval import RetrievalConfig, retrieve


@dataclass
class Case:
    query: str
    relevant_sections: list[str]


def load_cases(path: Path) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Case(query=c["query"], relevant_sections=c["relevant_sections"]) for c in raw]


def evaluate(G: nx.MultiDiGraph, cases: list[Case], k: int = 5, cfg: RetrievalConfig | None = None,
             embedder: Embedder | None = None, index: tuple[list[str], object] | None = None) -> dict:
    cfg = cfg or RetrievalConfig()
    if cfg.top_k < k:
        cfg = replace(cfg, top_k=k)
    rows, hits, rr_sum = [], 0, 0.0
    for case in cases:
        dense = dense_scores(embedder, index[0], index[1], case.query) if embedder and index else None
        result = retrieve(G, case.query, cfg, dense=dense)
        sections = [e["section"] for e in result["evidence"][:k]]
        rank = next((i for i, s in enumerate(sections, start=1)
                     if any(rel in s for rel in case.relevant_sections)), None)
        hit = rank is not None
        hits += hit
        rr_sum += 1.0 / rank if rank else 0.0
        rows.append(dict(query=case.query, rank=rank, top=sections[:3]))
    n = len(cases) or 1
    return dict(k=k, cases=len(cases), recall_at_k=round(hits / n, 4), mrr=round(rr_sum / n, 4),
                dense="PASS" if embedder and index else "NOT_RUN", rows=rows)
