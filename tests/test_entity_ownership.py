"""Same-named entities with different owners (checklist item: model-provided ownership must be kept)."""
from conftest import dependency_handler, extraction_handler
from dv_agent.graph import load_graph
from dv_agent.llm import FakeLLM
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest


def _ent(name, parent=""):
    return {"name": name, "kind": "field" if parent else "register", "aliases": [], "parent": parent}


def owned_fields(payload):
    text = payload["text"]
    if "Control Register" in text:
        return {"summary": "", "entities": [_ent("Control Register (CTRL)"), _ent("Enable", "Control Register (CTRL)")],
                "requirements": [{"statement": "CTRL Enable makes the counter decrement.",
                                  "quote": "the counter decrements on every clock cycle", "kind": "register",
                                  "entities": ["Enable"]}]}
    if "Reload Register" in text:
        return {"summary": "", "entities": [_ent("Reload Register (RELOAD)"), _ent("Enable", "Reload Register (RELOAD)"),
                                            _ent("Enable", "Status Register (STATUS)")],
                "requirements": [
                    {"statement": "RELOAD Enable gates the reload.", "quote": "The counter loads the RELOAD value",
                     "kind": "functional", "entities": ["Enable"]},
                    {"statement": "An Enable bit is set.", "quote": "the Enable bit is set", "kind": "functional",
                     "entities": ["Enable"]}]}
    return extraction_handler(payload)


def _build(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    stats = run_build_graph(out, FakeLLM({"spec_requirements": owned_fields,
                                          "requirement_dependencies": dependency_handler}))
    return stats, load_graph(out / GRAPH_FILE)


def test_same_named_fields_of_different_registers_stay_separate(spec_repo, tmp_path):
    _, G = _build(spec_repo, tmp_path)
    enables = {d["parent"]: n for n, d in G.nodes(data=True) if d.get("type") == "entity" and d["name"] == "Enable"}
    assert set(enables) == {"Control Register (CTRL)", "Reload Register (RELOAD)", "Status Register (STATUS)"}
    assert len(set(enables.values())) == 3


def test_reference_resolves_to_owner_named_in_requirement(spec_repo, tmp_path):
    _, G = _build(spec_repo, tmp_path)
    by_stmt = {d["statement"]: n for n, d in G.nodes(data=True) if d.get("type") == "requirement"}

    def mentioned(rid):
        return {G.nodes[v].get("parent") for _, v, k in G.out_edges(rid, keys=True) if k == "MENTIONS"}
    assert mentioned(by_stmt["CTRL Enable makes the counter decrement."]) == {"Control Register (CTRL)"}
    assert mentioned(by_stmt["RELOAD Enable gates the reload."]) == {"Reload Register (RELOAD)"}


def test_ambiguous_reference_is_not_linked(spec_repo, tmp_path):
    stats, G = _build(spec_repo, tmp_path)
    by_stmt = {d["statement"]: n for n, d in G.nodes(data=True) if d.get("type") == "requirement"}
    rid = by_stmt["An Enable bit is set."]
    assert not [k for _, _, k in G.out_edges(rid, keys=True) if k == "MENTIONS"]
    assert stats["requirements"]["rejected"] >= 1
