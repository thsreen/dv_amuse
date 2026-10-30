"""Deterministic slim index: mentions, stable ids, build/load/reuse, retrieval."""
import json

from dv_agent.pipeline import run_ingest
from dv_agent.retrieval.slim_index import INDEX_FILE, SlimIndex, build_index, extract_mentions, load_index, requirement_id


def test_extract_mentions_finds_signals_and_terms():
    mentions = extract_mentions("When `THRE` is set, wb_clk_i samples DATA_BUS_7 and done_flag fires.")
    assert "THRE" in mentions and "wb_clk_i" in mentions and "DATA_BUS_7" in mentions
    assert "done_flag" not in mentions  # single underscore: too generic
    assert mentions == sorted(set(mentions), key=mentions.index)  # deduped, stable order


def test_requirement_id_is_stable_and_chunk_scoped():
    assert requirement_id("CH-1", "the quick brown") == requirement_id("CH-1", "the quick brown")
    assert requirement_id("CH-1", "the quick brown") != requirement_id("CH-2", "the quick brown")
    assert requirement_id("CH-1", "the quick brown").startswith("REQ-")


def test_build_persists_and_load_reuses(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    first = build_index(out)
    assert (out / INDEX_FILE).is_file()
    assert first.search("reset value")
    second = load_index(out)
    assert second is not None
    assert second.search("reset value") == first.search("reset value")


def test_load_returns_none_when_stale_or_broken(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    assert load_index(out) is None  # nothing persisted yet
    build_index(out)
    assert load_index(out) is not None
    (out / INDEX_FILE).write_text("{broken", encoding="utf-8")
    assert load_index(out) is None
    build_index(out)
    saved = json.loads((out / INDEX_FILE).read_text(encoding="utf-8"))
    saved["chunks"]["CH-nope"] = "0" * 64
    (out / INDEX_FILE).write_text(json.dumps(saved), encoding="utf-8")
    assert load_index(out) is None  # hash set no longer matches chunks


def test_mentions_boost_relevant_chunks():
    chunks = {
        "CH-a": dict(chunk_id="CH-a", doc_path="d", pages=[1, 1], section="S",
                     text="The control register holds mode bits for later use.", text_sha256="a"),
        "CH-b": dict(chunk_id="CH-b", doc_path="d", pages=[1, 1], section="S",
                     text="Status flags report conditions as they occur.", text_sha256="b"),
    }
    mentions = {"CH-a": ["MODE_BITS"], "CH-b": []}
    index = SlimIndex(chunks, mentions)
    ranked = index.search("MODE_BITS")
    assert ranked and ranked[0][0] == "CH-a"


def test_materialize_creates_stable_requirements(spec_repo, tmp_path):
    from dv_agent.graph.graph import build_structure
    from dv_agent.ingest.ingest import load_chunks, load_manifest
    from dv_agent.pipeline import run_ingest
    from dv_agent.retrieval.slim_index import materialize_requirements, requirement_id
    from dv_agent.plan.testplan_context import requirement_record

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    G = build_structure(load_manifest(out), load_chunks(out))
    cid = next(n for n, d in G.nodes(data=True) if d.get("type") == "chunk")
    quote = " ".join(G.nodes[cid]["text"].split()[:12])
    assert len(quote) >= 8
    entries = [dict(text="Check it", cited_req_ids=[], cited_chunk_ids=[cid], quote=quote),
               dict(text="Check it again", cited_req_ids=[], cited_chunk_ids=[cid], quote=quote),
               dict(text="No quote", cited_req_ids=[], cited_chunk_ids=[cid], quote="")]
    rids = materialize_requirements(G, entries, kind="functional", model="fake", trace_id="t")
    assert rids[0] and rids[0] == rids[1] and rids[2] == ""
    assert entries[0]["cited_req_ids"] == [rids[0]]
    rec = requirement_record(G, rids[0])
    assert rec["quote"] in G.nodes[cid]["text"] and rec["citation"]["chunk_id"] == cid
    assert rids[0] == requirement_id(cid, rec["quote"])
    assert sum(1 for n, d in G.nodes(data=True) if d.get("type") == "requirement") == 1


def test_query_dependencies_caches_edges_on_graph(spec_repo, tmp_path):
    from dv_agent.graph.graph import build_structure
    from dv_agent.ingest.ingest import load_chunks, load_manifest
    from dv_agent.core.llm import FakeLLM
    from dv_agent.pipeline import run_ingest
    from dv_agent.retrieval.slim_index import materialize_requirements, query_dependencies
    from dv_agent.core.trace import Tracer

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    G = build_structure(load_manifest(out), load_chunks(out))
    cids = [n for n, d in G.nodes(data=True) if d.get("type") == "chunk"][:2]
    entries = [dict(text=f"Check {i}", cited_req_ids=[], cited_chunk_ids=[cid],
                    quote=" ".join(G.nodes[cid]["text"].split()[:12])) for i, cid in enumerate(cids)]
    rids = materialize_requirements(G, entries)
    assert all(rids)
    calls = []

    def dep_handler(payload):
        reqs = payload["requirements"]
        calls.append(payload)
        return {"edges": [dict(src=reqs[0]["req_id"], dst=reqs[1]["req_id"], type="DEPENDS_ON",
                               rationale="test", evidence_quote=" ".join(reqs[0]["quote"].split()[:6]))]}

    with Tracer(tmp_path / "t.jsonl", "t") as tracer:
        llm = FakeLLM({"requirement_dependencies": dep_handler})
        stats = query_dependencies(G, llm, tracer, rids, topic="checks")
        assert len(stats["edges"]) == 1 and stats["rejected"] == []
        a, b = sorted(rids)
        assert G.has_edge(a, b, key="DEPENDS_ON")
        again = query_dependencies(G, llm, tracer, rids)
        assert again["pairs"] == 0 and len(calls) == 1


def test_basic_build_skips_extraction_and_writes_index(spec_repo, tmp_path):
    from dv_agent.graph.graph import load_graph
    from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest
    from dv_agent.retrieval.slim_index import INDEX_FILE

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    stats = run_build_graph(out, None, mode="basic")
    assert stats["mode"] == "basic" and stats["slim_index"]["status"] == "PASS"
    assert (out / INDEX_FILE).is_file()
    G = load_graph(out / GRAPH_FILE)
    assert not any(d.get("type") == "requirement" for _, d in G.nodes(data=True))
    assert run_build_graph(out, None, mode="basic")["reused"] is True


def test_unknown_mode_is_rejected(spec_repo, tmp_path):
    import pytest

    from dv_agent.pipeline import run_build_graph, run_ingest

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    with pytest.raises(ValueError, match="unknown mode"):
        run_build_graph(out, None, mode="bogus")


def test_basic_build_never_calls_model_or_embedder(spec_repo, tmp_path):
    from dv_agent.core.llm import FakeLLM
    from dv_agent.pipeline import run_build_graph
    class ForbiddenEmbedder:
        def embed(self, texts):
            raise AssertionError("basic mode must not embed")
    out = tmp_path / "basic"
    run_ingest(spec_repo, out)
    llm = FakeLLM({})  # any unexpected model call fails
    result = run_build_graph(out, llm, mode="basic", embedder=ForbiddenEmbedder())
    assert result["mode"] == "basic" and result["llm"]["status"] == "NOT_RUN"
    assert result["slim_index"]["status"] == "PASS" and llm.calls == []
    assert run_build_graph(out, llm, mode="basic")["reused"]
