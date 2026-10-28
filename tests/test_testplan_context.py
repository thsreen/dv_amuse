import json

import pytest

from conftest import dependency_handler, extraction_handler, plan_handler, rerank_handler
from dv_agent.cli import main
from dv_agent.graph import load_graph
from dv_agent.llm import FakeLLM
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_context, run_features, run_ingest, run_test_plan
from dv_agent.planning import PlanConfig
from dv_agent.retrieval import RetrievalConfig
from dv_agent.testplan_context import BUNDLE_SCHEMA_VERSION, feature_index, fetch_context, requirement_context
from dv_agent.trace import read_trace


def _llm(**overrides):
    handlers = {"spec_requirements": extraction_handler, "requirement_dependencies": dependency_handler,
                "rerank_chunks": rerank_handler, "test_plan_items": plan_handler}
    handlers.update(overrides)
    return FakeLLM(handlers)


@pytest.fixture
def built(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm())
    return out, load_graph(out / GRAPH_FILE)


def _req(G, prefix):
    return next(n for n, d in G.nodes(data=True)
                if d.get("type") == "requirement" and d["statement"].startswith(prefix))


def test_topic_bundle_is_cited_and_includes_dependency_preconditions(built):
    _, G = built
    reload_id, enable_id = _req(G, "On reaching zero"), _req(G, "When CTRL.Enable")
    b = fetch_context(G, "counter reload value when it reaches zero", max_requirements=1)
    assert b["schema_version"] == BUNDLE_SCHEMA_VERSION and b["authority"] == "specification"
    assert [r["req_id"] for r in b["requirements"]] == [reload_id]
    cit = b["requirements"][0]["citation"]
    assert cit["doc_path"].endswith("tmr32_spec.txt") and cit["page"] == 3 and cit["chunk_id"]
    assert [r["req_id"] for r in b["dependency_requirements"]] == [enable_id]
    dep = b["dependencies"][0]
    assert (dep["src"], dep["type"], dep["dst"]) == (reload_id, "DEPENDS_ON", enable_id)
    assert dep["status"] == "INFERRED" and dep["dst_in_scope"] is False
    assert any(i["kind"] == "unreviewed_dependency" for i in b["open_items"])
    assert all(n["navigation_only"] for n in b["navigation"])
    assert b["evidence"][0]["text"] and b["evidence"][0]["explanation"]


def test_requirement_bundle_puts_focus_first_with_lineage(built):
    _, G = built
    reload_id = _req(G, "On reaching zero")
    b = requirement_context(G, reload_id)
    assert b["focus_requirement"] == reload_id and b["requirements"][0]["req_id"] == reload_id
    assert G.nodes[reload_id]["chunk_id"] in {s["chunk_id"] for s in b["lineage"]["sources"]}
    with pytest.raises(KeyError):
        requirement_context(G, "REQ-missing")


def test_feature_index_orders_sections_and_lists_requirements(built):
    _, G = built
    idx = feature_index(G)
    titles = [s["title"] for s in idx["sections"]]
    assert titles.index("2 Registers") < titles.index("2.1 Control Register (CTRL)") < titles.index(
        "2.2 Reload Register (RELOAD)") < titles.index("3 Interrupts")
    ctrl = next(s for s in idx["sections"] if s["title"].startswith("2.1"))
    assert len(ctrl["requirement_ids"]) == 2 and any("CTRL" in e for e in ctrl["entities"])
    assert idx["requirements_total"] == 4
    assert all(c["navigation_only"] for c in idx["communities"])


def test_run_context_is_traced_with_fact_ids(built):
    out, G = built
    b = run_context(out, topic="IRQ asserted until STATUS bit written")
    span = next(r for r in read_trace(out / "trace.jsonl", b["trace_id"]) if r["name"] == "fetch_context")
    assert span["metadata"]["fact_ids"] == [r["req_id"] for r in b["requirements"] + b["dependency_requirements"]]
    with pytest.raises(ValueError):
        run_context(out)


def test_cli_context_and_features(built, tmp_path, capsys):
    out, G = built
    save = tmp_path / "bundle.json"
    assert main(["context", "reload value", "--out", str(out), "--save", str(save)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert json.loads(save.read_text())["requirements"] == printed["requirements"]
    assert main(["context", "--requirement", _req(G, "On reaching zero"), "--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "requirement"
    assert main(["context", "--out", str(out)]) == 2
    assert main(["context", "--requirement", "REQ-missing", "--out", str(out)]) == 2
    capsys.readouterr()
    assert main(["features", "--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["sections"] == run_features(out)["sections"]


def test_planner_offers_dependency_preconditions_for_citation(built):
    out, G = built
    reload_id, enable_id = _req(G, "On reaching zero"), _req(G, "When CTRL.Enable")
    seen = {}

    def capture(payload):
        seen.update(payload)
        return plan_handler(payload)
    run_test_plan(out, [reload_id], _llm(test_plan_items=capture), PlanConfig(retrieval=RetrievalConfig()))
    assert enable_id in {r["req_id"] for r in seen["requirements"]}
    assert seen["dependencies"][0]["dst"] == enable_id and seen["dependencies"][0]["status"] == "INFERRED"
