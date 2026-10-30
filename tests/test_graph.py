import pytest

from dv_agent.ingest.extract import locate_quote
from dv_agent.graph.graph import attach_artifact, lineage, load_graph, save_graph
from dv_agent.pipeline import GRAPH_FILE, TRACE_FILE, run_build_graph, run_ingest
from dv_agent.core.trace import Tracer, read_trace


@pytest.fixture
def built(spec_repo, tmp_path, fake_llm):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    stats = run_build_graph(out, fake_llm, mode="graph")
    return out, stats, load_graph(out / GRAPH_FILE)


def _req(G, prefix):
    return next(n for n, d in G.nodes(data=True)
                if d.get("type") == "requirement" and d["statement"].startswith(prefix))


def test_locate_quote_tolerates_typography_and_whitespace():
    text = "When '1' the  counter\ndecrements - fast"
    assert locate_quote(text, "When ‘1’ the counter decrements – fast") == (0, len(text))
    assert locate_quote(text, "not there") is None


def test_requirements_are_quote_backed_and_bad_quotes_rejected(built):
    _, stats, G = built
    assert stats["requirements"]["requirements"] == 4
    assert stats["requirements"]["rejected"] == 1
    enable = G.nodes[_req(G, "When CTRL.Enable")]
    assert enable["quote"] == "When '1' the counter decrements on every clock cycle"
    chunk = G.nodes[enable["chunk_id"]]
    assert chunk["text"][enable["quote_start"] - chunk["char_start"]:
                         enable["quote_end"] - chunk["char_start"]] == enable["quote"]
    assert enable["status"] == "DOCUMENTED" and enable["review_status"] == "NOT_REVIEWED"
    assert enable["page"] == 2


def test_entities_merge_across_chunks_via_aliases(built):
    _, _, G = built
    ctrl = [n for n, d in G.nodes(data=True) if d.get("type") == "entity" and "CTRL" in d["name"]]
    assert len(ctrl) == 1
    mentions = {u for u, _, k in G.in_edges(ctrl[0], keys=True) if k == "MENTIONS"}
    assert _req(G, "On reaching zero") in mentions and _req(G, "CTRL resets") in mentions


def test_dependency_edges_need_verbatim_evidence(built):
    _, stats, G = built
    reload_id, enable_id = _req(G, "On reaching zero"), _req(G, "When CTRL.Enable")
    edge = G.edges[reload_id, enable_id, "DEPENDS_ON"]
    assert edge["status"] == "INFERRED" and edge["evidence_req_id"] == reload_id
    assert not G.has_edge(enable_id, reload_id, key="REFINES")
    assert stats["dependencies"]["rejected"] >= 1


def test_artifact_lineage_lists_facts_sources_and_is_traced(built):
    out, _, G = built
    reload_id, enable_id = _req(G, "On reaching zero"), _req(G, "When CTRL.Enable")
    with Tracer(out / TRACE_FILE, "generate_sva") as tracer:
        result = attach_artifact(G, tracer, "SVA-0001", "assertion", [reload_id],
                                 content="assert property (...);")
    roles = {f["req_id"]: f["role"] for f in result["facts"]}
    assert roles == {reload_id: "basis", enable_id: "dependency"}
    assert {s["chunk_id"] for s in result["sources"]} == {G.nodes[reload_id]["chunk_id"],
                                                          G.nodes[enable_id]["chunk_id"]}
    assert result["review_status"] == "NEEDS_REVIEW"
    span = next(r for r in read_trace(out / TRACE_FILE, tracer.trace_id)
                if r["name"] == "lineage:SVA-0001")
    assert span["metadata"]["fact_ids"] == [reload_id, enable_id]
    assert lineage(G, "SVA-0001")["facts"] == result["facts"]


def test_requirement_spans_exist_in_trace(built):
    out, stats, G = built
    records = {r["span_id"]: r for r in read_trace(out / TRACE_FILE, stats["trace_id"])}
    req = G.nodes[_req(G, "When CTRL.Enable")]
    span = records[req["span_id"]]
    assert span["name"] == f"extract:{req['chunk_id']}"
    gens = [r for r in records.values() if r["type"] == "generation" and r["parent_id"] == span["span_id"]]
    assert len(gens) == 1 and gens[0]["output"]["requirements"]


def test_graph_roundtrip_and_structural_build_without_llm(built, spec_repo, tmp_path):
    out, _, G = built
    save_graph(G, tmp_path / "copy.json")
    H = load_graph(tmp_path / "copy.json")
    assert H.number_of_nodes() == G.number_of_nodes() and H.number_of_edges() == G.number_of_edges()
    out2 = tmp_path / "structural"
    run_ingest(spec_repo, out2)
    stats = run_build_graph(out2, None, mode="graph")
    assert stats["llm"]["status"] == "NOT_RUN"
    assert "requirement" not in stats["nodes"] and stats["nodes"]["chunk"] > 0
