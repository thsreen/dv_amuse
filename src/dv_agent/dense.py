"""Dense embeddings held in an in-process NumPy index (no vector database).

HashEmbedder is a deterministic offline stand-in (signed feature hashing over words and bigrams).
MetaEmbedder calls the Meta embeddings endpoint and is unverified until a key is supplied.
"""
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Protocol

import networkx as nx
import numpy as np

from .fsutil import atomic_write_text
from .progress import emit
from .retrieval import node_text, tokenize


class Embedder(Protocol):
    model: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return (m / np.where(norms == 0, 1.0, norms)).astype(np.float32)


class HashEmbedder:
    def __init__(self, dim: int = 512):
        self.dim = dim
        self.model = f"hash-signed-{dim}"

    def _features(self, text: str) -> list[str]:
        words = tokenize(text)
        return words + [a + "_" + b for a, b in zip(words, words[1:])]

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for feat in self._features(text):
                h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "big")
                out[row, h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        return _normalize(out)


class MetaEmbedder:
    """Embeddings via the OpenAI-compatible endpoint; model and endpoint come from env."""

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, client=None, batch: int = 64, timeout: float = 60.0):
        self.model = model or os.getenv("META_EMBED_MODEL", "")
        self.api_key = api_key if api_key is not None else os.getenv("MODEL_API_KEY", "").strip()
        self.base_url = base_url or os.getenv("META_BASE_URL", "https://api.meta.ai/v1")
        self.batch = batch
        self.timeout = timeout
        self._client = client
        self.dim = 0

    def _get_client(self):
        if self._client is None:
            import openai
            self._client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url,
                                         timeout=self.timeout, max_retries=0)
        return self._client

    def embed(self, texts: list[str]) -> np.ndarray:
        if not self.model:
            raise RuntimeError("META_EMBED_MODEL is not configured")
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        rows = []
        client = self._get_client()
        batches = (len(texts) + self.batch - 1) // self.batch
        emit(f"embedding {len(texts)} texts in {batches} batches with {self.model}")
        for num, i in enumerate(range(0, len(texts), self.batch), 1):
            emit(f"embedding batch [{num}/{batches}]")
            import openai
            for attempt in range(1, 6):
                try:
                    resp = client.embeddings.create(model=self.model, input=texts[i:i + self.batch])
                    break
                except (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
                        openai.InternalServerError):
                    if attempt == 5:
                        raise
                    emit(f"embedding batch [{num}/{batches}] retry {attempt + 1}/5")
                    time.sleep(2 ** attempt)
            rows += [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
        arr = np.asarray(rows, dtype=np.float32)
        self.dim = arr.shape[1]
        return _normalize(arr)


def indexable_nodes(G: nx.MultiDiGraph) -> list[str]:
    return sorted(n for n, d in G.nodes(data=True) if d.get("layer") in (1, 2, 3) and node_text(d))


def build_index(G: nx.MultiDiGraph, embedder: Embedder) -> tuple[list[str], np.ndarray]:
    ids = indexable_nodes(G)
    matrix = embedder.embed([node_text(G.nodes[i]) for i in ids])
    return ids, matrix


def save_index(path: Path, model: str, ids: list[str], matrix: np.ndarray) -> None:
    path.mkdir(parents=True, exist_ok=True)
    np.save(path / "vectors.npy", matrix)
    atomic_write_text(path / "index.json", json.dumps({"model": model, "ids": ids}, indent=1))


def load_index(path: Path) -> tuple[str, list[str], np.ndarray]:
    meta = json.loads((path / "index.json").read_text(encoding="utf-8"))
    return meta["model"], meta["ids"], np.load(path / "vectors.npy")


def dense_scores(embedder: Embedder, ids: list[str], matrix: np.ndarray, query: str) -> dict[str, float]:
    qv = embedder.embed([query])[0]
    sims = matrix @ qv
    return {nid: float(s) for nid, s in zip(ids, sims) if s > 0}
