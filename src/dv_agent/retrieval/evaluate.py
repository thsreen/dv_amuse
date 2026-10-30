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
    kind: str = ""


def load_cases(path: Path) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Case(query=c["query"], relevant_sections=c["relevant_sections"], kind=c.get("type", "")) for c in raw]


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
        rows.append(dict(query=case.query, kind=case.kind, rank=rank, top=sections[:3]))
    n = len(cases) or 1
    return dict(k=k, cases=len(cases), recall_at_k=round(hits / n, 4), mrr=round(rr_sum / n, 4),
                dense="PASS" if embedder and index else "NOT_RUN", rows=rows)


def compare(G: nx.MultiDiGraph, cases: list[Case], ks: list[int], variants: dict[str, RetrievalConfig],
            embedder: Embedder | None = None, index: tuple[list[str], object] | None = None) -> dict:
    """Recall@k and MRR for each named retrieval configuration, plus per-query-type recall at the largest k."""
    out: dict = {}
    for name, cfg in variants.items():
        by_k = {k: evaluate(G, cases, k, cfg, embedder, index) for k in ks}
        top = by_k[max(ks)]
        kinds: dict[str, list[bool]] = {}
        for row in top["rows"]:
            kinds.setdefault(row["kind"] or "unlabelled", []).append(row["rank"] is not None)
        out[name] = dict(
            metrics={k: dict(recall_at_k=r["recall_at_k"], mrr=r["mrr"]) for k, r in by_k.items()},
            recall_by_type={t: round(sum(v) / len(v), 4) for t, v in sorted(kinds.items())},
            misses=[dict(query=r["query"], top=r["top"]) for r in top["rows"] if r["rank"] is None],
            dense=top["dense"])
    return dict(cases=len(cases), ks=ks, variants=out)


def format_table(result: dict) -> str:
    ks = result["ks"]
    head = "| variant | " + " | ".join(f"recall@{k}" for k in ks) + " | " + " | ".join(f"MRR@{k}" for k in ks) + " |"
    lines = [f"Labelled cases: {result['cases']}", "", head, "|" + "---|" * (1 + 2 * len(ks))]
    for name, v in result["variants"].items():
        m = v["metrics"]
        lines.append(f"| {name} | " + " | ".join(f"{m[k]['recall_at_k']:.2f}" for k in ks) + " | "
                     + " | ".join(f"{m[k]['mrr']:.2f}" for k in ks) + " |")
    return "\n".join(lines)
