import json

import pytest

from dv_agent.pipeline import run_build_graph, run_ingest, run_testplan_doc
from dv_agent.testplan_doc import load_template
from dv_agent.trace import read_trace
from rtl_agent.graph import build_graph, save_graph
from test_rtl_graph import DESIGN
from test_testplan_doc import _llm, entries_handler, strategy_handler


@pytest.fixture
def inputs(spec_repo, tmp_path):
    out = tmp_path / "plan"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm())
    rtl = tmp_path / "design.sv"
    rtl.write_text(DESIGN)
    graph = tmp_path / "rtl_graph.json"
    save_graph(build_graph([rtl], "top"), graph)
    return out, graph


def observation(payload):
    context = payload["context"]
    node = next(n for n in context["nodes"] if n["id"] == "SIG:top.right.q")
    excerpt = next(c for c in context["evidence"] if "posedge clk" in c["text"])
    return dict(observations=[dict(text="Potential clock-domain transfer into top.right.q requires designer review.",
                                   kind="crossing", suggested_verification="Exercise source/destination clocks and reset during transfers.",
                                   inference_reason="The cited RTL shows signals crossing the candidate clock domains.",
                                   designer_question="Which transfer/reset assumptions and synchronization checks are required?",
                                   spec_relationship="NOT_FOUND_IN_RETRIEVED_SPEC", cited_spec_ids=[],
                                   cited_rtl_node_ids=[node["id"]], cited_rtl_excerpt_ids=[excerpt["id"]])])


def fetch(payload):
    return dict(queries=["top.right.q clock reset dependencies"] if payload["round"] == 1 else [], reason="focused dependency evidence")


def support(payload):
    return dict(judgements=[dict(id=o["id"], supported=True, reason="") for o in payload["observations"]])


def strategy(payload):
    result = strategy_handler(payload)
    if payload.get("rtl_observations"):
        result["rtl_observation_actions"] = [dict(observation_id=o["id"], handling="Add reviewed clock/reset transfer scenarios.",
                                                   agents=[result["agents"][0]["name"]])
                                               for o in payload["rtl_observations"]["entries"]]
    return result


def entries(payload):
    result = entries_handler(payload)
    item = result["entries"][0]
    if payload["section"]["id"] == "checks":
        item["cited_req_ids"] = [r["req_id"] for r in payload["requirements"]]
    if payload.get("rtl_observations"):
        oid = payload["rtl_observations"]["entries"][0]["id"]
        item.update(cited_rtl_observation_ids=[oid], provenance="DOCUMENTED")
    return dict(entries=[item])


def model(**overrides):
    return _llm(**(dict(rtl_observation_fetch=fetch, rtl_observations=observation, rtl_observation_claims=support,
                       testplan_strategy=strategy, testplan_entries=entries) | overrides))


def doc(out):
    return json.loads((out / "testplan_doc.json").read_text())


def test_observations_fetch_graph_and_drive_strategy_and_plan(inputs):
    out, graph = inputs
    llm = model()
    run_testplan_doc(out, llm, rtl_graph_path=graph)
    result = doc(out)
    section = next(s for s in result["sections"] if s["id"] == "rtl_observations")
    obs = section["entries"][0]
    assert section["status"] == "PASS" and len(section["fetches"]) == 2
    assert obs["review_status"] == "NEEDS_REVIEW" and obs["review_owner"] == "RTL_DESIGN_ENGINEER"
    assert obs["gap_status"] == "UNCONFIRMED" and obs["provenance"] == "INFERRED"
    strat = next(s for s in result["sections"] if s["id"] == "strategy")["strategy"]
    assert strat["rtl_observation_actions"][0]["observation_id"] == obs["id"]
    for sid in ("stimulus", "checks", "coverage", "callouts"):
        item = next(s for s in result["sections"] if s["id"] == sid)["entries"][0]
        assert item["cited_rtl_observation_ids"] == [obs["id"]]
        assert item["provenance"] == "INFERRED" and item["review_owner"] == "RTL_DESIGN_ENGINEER"
    assert any(name == "rtl_observation_claims" for name, _ in llm.calls)
    md = (out / "testplan_doc.md").read_text()
    assert md.index("Observations from RTL") < md.index("High Level Verification Strategy")
    assert "RTL design engineer review required" in md and obs["id"] in md
    assert any(r["name"] == "fetch_rtl_graph" for r in read_trace(out / "trace.jsonl"))


def test_no_graph_does_not_read_rtl_and_reuses(inputs, monkeypatch):
    out, _ = inputs
    monkeypatch.setattr("rtl_agent.graph.load_graph", lambda *a: pytest.fail("must not load RTL without opt-in"))
    first = model()
    run_testplan_doc(out, first)
    assert doc(out)["rtl_observations"]["status"] == "NOT_RUN"
    assert not any(name.startswith("rtl_observation") for name, _ in first.calls)
    second = model()
    assert run_testplan_doc(out, second)["reused"] and second.calls == []


def test_unknown_citations_are_withheld_after_bounded_repair(inputs):
    out, graph = inputs
    def invalid(payload):
        result = observation(payload)
        result["observations"][0]["cited_rtl_excerpt_ids"] = ["SRC:invented"]
        return result
    llm = model(rtl_observations=invalid)
    run_testplan_doc(out, llm, rtl_graph_path=graph)
    result = doc(out)["rtl_observations"]
    assert result["status"] == "BLOCKED" and result["entries"] == []
    assert result["repair"]["unresolved"] and len(result["repair"]["refusals"]) == 2
    assert sum(name == "rtl_observations" for name, _ in llm.calls) == 3


def test_supported_citation_cannot_bypass_independent_claim_check(inputs):
    out, graph = inputs
    def bad(payload):
        result = observation(payload)
        if "refusal" not in payload:
            result["observations"][0]["text"] = "The crossing is proven safe."
        return result
    def judge(payload):
        return dict(judgements=[dict(id=o["id"], supported="proven safe" not in o["text"], reason="No CDC proof in static RTL")
                                for o in payload["observations"]])
    run_testplan_doc(out, model(rtl_observations=bad, rtl_observation_claims=judge), rtl_graph_path=graph)
    result = doc(out)["rtl_observations"]
    assert result["status"] == "PASS" and len(result["repair"]["refusals"]) == 1
    assert "proven safe" not in result["entries"][0]["text"]


def test_graph_changes_and_scope_invalidate_testplan_cache(inputs):
    out, graph = inputs
    run_testplan_doc(out, model(), rtl_graph_path=graph)
    assert run_testplan_doc(out, model(), rtl_graph_path=graph)["reused"]
    from rtl_agent.graph import load_graph
    G = load_graph(graph)
    G.nodes["SIG:top.right.q"]["description"] = "changed snapshot"
    save_graph(G, graph)
    assert not run_testplan_doc(out, model(), rtl_graph_path=graph)["reused"]
    assert not run_testplan_doc(out, model(), rtl_graph_path=graph, rtl_scope="top.right")["reused"]


def test_template_requires_rtl_observations_before_strategy(tmp_path):
    template = load_template()
    sections = template["sections"]
    sections[3], sections[4] = sections[4], sections[3]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(template))
    with pytest.raises(ValueError, match="must precede strategy"):
        load_template(path)


def test_strategy_must_handle_each_observation(inputs):
    out, graph = inputs
    llm = model(testplan_strategy=strategy_handler)
    run_testplan_doc(out, llm, rtl_graph_path=graph)
    st = next(s for s in doc(out)["sections"] if s["id"] == "strategy")["strategy"]
    assert any("no strategy handling action" in p for p in st["repair"]["unresolved"])
