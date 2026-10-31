"""Deterministic chunk index for basic (graph-free) mode: no LLM calls.

Each chunk is searchable by plain terms plus heuristically extracted mentions
(signals, registers, backticked terms). Retrieval quality comes from lexical
matching plus mention boosting; traceability still comes from verified verbatim
quotes, exactly as in graph mode.
"""
import hashlib
import json
import re
from pathlib import Path

from ..ingest.extract import DEPENDENCY_INSTRUCTIONS, _apply_dependencies, _dependency_schema, locate_quote
from ..graph.graph import DEPENDENCY_EDGES, add_edge, page_of
from ..ingest.ingest import load_chunks
from .retrieval import BM25, RetrievalConfig, tokenize

INDEX_VERSION = 1
INDEX_FILE = "slim_index.json"

MENTION_PATTERNS = (
    re.compile(r"`([^`]{1,64})`"),                       # `backticked` terms
    re.compile(r"\b[A-Z][A-Z0-9_]{1,31}\b"),              # uppercase identifiers
    re.compile(r"\b[a-z]+(?:_[a-z0-9]+){2,}\b"),          # underscore-separated identifiers
)
MENTION_BOOST = 3  # mention tokens repeat this often in the indexed doc


def requirement_id(chunk_id: str, quote: str) -> str:
    """Stable requirement identity shared with graph mode: same quote, same id."""
    return "REQ-" + hashlib.sha256(f"{chunk_id}|{quote}".encode()).hexdigest()[:10]


def extract_mentions(text: str) -> list[str]:
    """Deterministic signal/register/term mentions, deduplicated in first-seen order."""
    found: list[str] = []
    for pattern in MENTION_PATTERNS:
        for match in pattern.finditer(text):
            term = match.group(1) if pattern.groups else match.group(0)
            term = " ".join(term.split())
            if term and term not in found:
                found.append(term)
    return found


class SlimIndex:
    """In-memory BM25 over chunk terms + boosted mention tokens."""

    def __init__(self, chunks: dict[str, dict], mentions: dict[str, list[str]],
                 cfg: RetrievalConfig | None = None):
        cfg = cfg or RetrievalConfig()
        self.chunks = chunks
        self.mentions = mentions
        docs = {}
        for cid, chunk in chunks.items():
            tokens = tokenize(chunk["section"] + " " + chunk["text"])
            for term in mentions.get(cid, []):
                tokens.extend(tokenize(term) * MENTION_BOOST)
            docs[cid] = tokens
        self.bm25 = BM25(docs, cfg.bm25_k1, cfg.bm25_b)

    def search(self, query: str, top_k: int = 8) -> list[tuple[str, float]]:
        ranked = self.bm25.score(tokenize(query))
        return sorted(ranked.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]


def build_index(out: Path) -> SlimIndex:
    """Build the index from chunks.jsonl and persist it for reuse."""
    chunks, mentions, hashes = {}, {}, {}
    for chunk in load_chunks(out):
        cid = chunk.chunk_id
        chunks[cid] = dict(chunk_id=cid, doc_path=chunk.doc_path,
                           pages=[chunk.page_start, chunk.page_end],
                           section=" > ".join(chunk.section_path), text=chunk.text,
                           text_sha256=chunk.text_sha256)
        mentions[cid] = extract_mentions(chunk.text)
        hashes[cid] = chunk.text_sha256
    (out / INDEX_FILE).write_text(json.dumps(
        dict(version=INDEX_VERSION, chunks=hashes, mentions=mentions)), encoding="utf-8")
    return SlimIndex(chunks, mentions)


def load_index(out: Path) -> SlimIndex | None:
    """Load a persisted index, or None when missing or stale (caller rebuilds)."""
    path = out / INDEX_FILE
    if not path.is_file():
        return None
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if saved.get("version") != INDEX_VERSION:
        return None
    try:
        live = {c.chunk_id: c for c in load_chunks(out)}
    except (OSError, ValueError):
        return None
    if {cid: c.text_sha256 for cid, c in live.items()} != saved.get("chunks"):
        return None
    chunks = {cid: dict(chunk_id=cid, doc_path=c.doc_path, pages=[c.page_start, c.page_end],
                        section=" > ".join(c.section_path), text=c.text,
                        text_sha256=c.text_sha256) for cid, c in live.items()}
    return SlimIndex(chunks, saved.get("mentions", {}))


MIN_QUOTE_CHARS = 8  # mirrors ExtractConfig.min_quote_chars: shorter quotes are not verifiable


def materialize_requirements(G, entries: list[dict], *, kind: str = "functional", model: str = "",
                             trace_id: str = "") -> list[str]:
    """Create requirement nodes from verified entry quotes (lazy cited generation).

    Same node shape and quote-derived identity as graph-mode extraction, so a quote
    cited in basic mode yields the same REQ id it would have in graph mode. Entries are
    updated in place with the materialized cited_req_ids; returns one req id per entry
    ("" when the entry has no verifiable quote).
    """
    rids = []
    for e in entries:
        quote = (e.get("quote") or "").strip()
        rid = ""
        if len(quote) >= MIN_QUOTE_CHARS:
            for cid in e.get("cited_chunk_ids", []):
                if cid not in G:
                    continue
                n = G.nodes[cid]
                loc = locate_quote(n["text"], quote)
                if loc is None:
                    continue
                exact = n["text"][loc[0]:loc[1]]
                start = n["char_start"] + loc[0]
                rid = requirement_id(cid, exact)
                if rid not in G:
                    G.add_node(rid, layer=2, type="requirement", statement=e["text"].strip(),
                               quote=exact, quote_start=start, quote_end=n["char_start"] + loc[1],
                               kind=kind, chunk_id=cid, doc_id=n["doc_id"], doc_path=n["doc_path"],
                               page=page_of(G, n["doc_id"], start),
                               section=" > ".join(n["section_path"]),
                               status="INFERRED" if n.get("authority") == "RTL_INFERRED" else "DOCUMENTED",
                               interpretation="INFERRED",
                               review_status="NEEDS_REVIEW" if n.get("authority") == "RTL_INFERRED" else "NOT_REVIEWED",
                               model=model, response_id="", trace_id=trace_id, span_id="")
                    add_edge(G, rid, cid, "DERIVED_FROM", status=G.nodes[rid]["status"])
                if rid not in e.get("cited_req_ids", []):
                    e["cited_req_ids"] = list(e.get("cited_req_ids", [])) + [rid]
                break
        rids.append(rid)
    return rids


def _pair_covered(G, a: str, b: str) -> bool:
    return any(G.has_edge(a, b, key=t) or G.has_edge(b, a, key=t) for t in DEPENDENCY_EDGES)


def query_dependencies(G, llm, tracer, req_ids: list[str], *, topic: str = "") -> dict:
    """One on-demand dependency call over the given requirements; edges cached on G.

    Reuses graph-mode instructions, schema, and edge application. Pairs already joined
    by a dependency edge are skipped, so repeat queries over the same set are free.
    """
    reqs = sorted({r for r in req_ids if r in G and G.nodes[r].get("type") == "requirement"})
    pairs = [(a, b) for i, a in enumerate(reqs) for b in reqs[i + 1:] if not _pair_covered(G, a, b)]
    stats = dict(requirements=len(reqs), pairs=len(pairs), edges=[], rejected=[], cached=len(reqs) * (len(reqs) - 1) // 2 - len(pairs))
    if not pairs:
        return stats
    with tracer.span("slim_dependencies", input={"topic": topic, "requirements": reqs}) as span:
        result = llm.structured(name="requirement_dependencies", instructions=DEPENDENCY_INSTRUCTIONS,
                                payload={"entity": topic, "requirements": [
                                    {"req_id": r, "statement": G.nodes[r]["statement"],
                                     "quote": G.nodes[r]["quote"], "section": G.nodes[r]["section"]}
                                    for r in reqs]},
                                schema=_dependency_schema(reqs), tracer=tracer)
        added, rejected = _apply_dependencies(G, set(reqs), result, span, tracer, "")
        stats["edges"], stats["rejected"] = added, rejected
        span.update(output={"added": added, "rejected": rejected})
    return stats
