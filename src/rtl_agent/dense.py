"""Optional in-process embeddings index. Providers are explicit; no built-in network calls."""
import hashlib
import json
from pathlib import Path
from typing import Protocol

import numpy as np

from .fsutil import atomic_write_text
from .graph import graph_data
from .retrieval import node_text
from .source import RTLExtractionError


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def fingerprint(G) -> str:
    return hashlib.sha256(json.dumps(graph_data(G), sort_keys=True).encode()).hexdigest()


def make_index(G, model: str, vectors: dict[str, list[float]]) -> dict:
    if not model or not vectors or len(vectors) > 20_000:
        raise RTLExtractionError("dense index needs a model and 1..20000 vectors")
    if any(n not in G or G.nodes[n].get("layer") != 2 for n in vectors):
        raise RTLExtractionError("dense vectors must reference semantic nodes in this graph")
    ids = sorted(vectors)
    try:
        matrix = np.asarray([vectors[n] for n in ids], dtype=float)
    except (TypeError, ValueError) as exc:
        raise RTLExtractionError("dense vectors must have a consistent numeric dimension") from exc
    if (matrix.ndim != 2 or not 1 <= matrix.shape[1] <= 4096 or matrix.size > 4_000_000
            or not np.isfinite(matrix).all() or (np.linalg.norm(matrix, axis=1) == 0).any()):
        raise RTLExtractionError("dense vectors are empty, nonfinite, zero, or exceed index budgets")
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    return dict(graph_fingerprint=fingerprint(G), model=model, dimension=matrix.shape[1],
                vectors={n: matrix[i].tolist() for i, n in enumerate(ids)})


def build_index(G, embedder: Embedder, *, batch_size: int = 16) -> dict:
    """Opt-in adapter for a configured embedding provider, batched with bounded inputs."""
    if not 1 <= batch_size <= 64:
        raise RTLExtractionError("embedding batch size must be 1..64")
    ids = sorted(n for n, d in G.nodes(data=True) if d.get("layer") == 2)
    vectors = {}
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        result = embedder.embed([node_text(G, n)[:1600] for n in batch])
        if len(result) != len(batch):
            raise RTLExtractionError("embedding provider returned the wrong vector count")
        vectors.update(zip(batch, result))
    return make_index(G, embedder.model, vectors)


def dense_scores(G, index: dict, query_vector: list[float], *, model: str) -> dict[str, float]:
    if index.get("graph_fingerprint") != fingerprint(G) or index.get("model") != model:
        raise RTLExtractionError("embedding index graph/model mismatch; rebuild the index")
    validated = make_index(G, model, index["vectors"])
    vector = np.asarray(query_vector, dtype=float)
    if (vector.ndim != 1 or vector.size != validated["dimension"] or not np.isfinite(vector).all()
            or np.linalg.norm(vector) == 0):
        raise RTLExtractionError("invalid query embedding dimension/value")
    vector /= np.linalg.norm(vector)
    return {n: max(0., float(np.dot(v, vector))) for n, v in validated["vectors"].items()}


def save_index(index: dict, path: Path):
    atomic_write_text(path, json.dumps(index, indent=2) + "\n")
