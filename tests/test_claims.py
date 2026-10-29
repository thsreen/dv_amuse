"""Claims check: an exact citation does not make a claim true; a separate judge call must agree."""
import json

import pytest

from dv_agent.claims import entry_claims
from dv_agent.graph import load_graph
from dv_agent.llm import LLMError
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_testplan_doc
from test_testplan_doc import _llm


@pytest.fixture
def run(spec_repo, tmp_path):
    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm())
    return out


def _ctrl_chunk(payload):
    return next(c["chunk_id"] for c in payload["chunks"] if "Control Register" in c["text"])


def clean_entries(contradiction_until_repaired=True, always_wrong=False):
    """Deterministically valid entries; stimulus claims CTRL resets to FFh (the cited text says 00h)."""
    def handler(payload):
        chunks = [c["chunk_id"] for c in payload["chunks"]]
        entry = {"text": f"{payload['section']['id']} behaviour is exercised", "kind": None, "provenance": "INFERRED",
                 "cited_req_ids": [], "cited_chunk_ids": chunks[:1], "details": []}
        kinds = {"feature_description": "purpose", "stimulus": "directed_test", "checks": "agent_scoreboard",
                 "coverage": "covergroup", "callouts": "reuse", "assumptions": "assumption", "questions": "question"}
        entry["kind"] = kinds[payload["section"]["id"]]
        entries = [entry]
        if payload["section"]["id"] == "stimulus" and any("Control Register" in c["text"] for c in payload["chunks"]):
            wrong = always_wrong or ("refusal" not in payload and contradiction_until_repaired)
            entries.append({"text": f"Reset leaves CTRL at {'FFh' if wrong else '00h'}", "kind": "directed_test",
                            "provenance": "DOCUMENTED", "cited_req_ids": [], "cited_chunk_ids": [_ctrl_chunk(payload)],
                            "details": []})
        if payload["section"]["id"] == "checks":  # cite every coverage target so only the claims check matters
            entries += [{"text": f"check {r['req_id']}", "kind": "agent_scoreboard", "provenance": "INFERRED",
                         "cited_req_ids": [r["req_id"]], "cited_chunk_ids": chunks[:1], "details": []}
                        for r in payload.get("uncovered_requirements", [])]
        return {"entries": entries}
    return handler


def judge_ffh(payload):
    """The judge reads the claim against the quotes; FFh contradicts the cited 'Reset Value: 00h'."""
    out = []
    for c in payload["claims"]:
        wrong = "FFh" in c["claim"] and any("00h" in s["text"] for s in c["sources"])
        out.append({"id": c["id"], "supported": not wrong, "reason": "the cited text gives 00h" if wrong else ""})
    return {"judgements": out}


def _section(out, sid):
    return next(s for s in json.loads((out / "testplan_doc.json").read_text())["sections"] if s["id"] == sid)


def test_exact_quote_with_contradictory_claim_is_refused_and_repaired(run):
    llm = _llm(testplan_entries=clean_entries(), claims_check=judge_ffh)
    run_testplan_doc(run, llm)
    stim = _section(run, "stimulus")
    refusal = stim["repair"]["refusals"][0]["problems"]
    assert any("claims check" in p and "FFh" in p for p in refusal)
    assert stim["repair"]["unresolved"] == []
    assert any(e["text"] == "Reset leaves CTRL at 00h" and e["provenance"] == "DOCUMENTED" for e in stim["entries"])
    assert stim["claims_check"]["status"] == "PASS" and stim["claims_check"]["downgraded"] == 0
    assert any(name == "claims_check" for name, _ in llm.calls)


def test_claim_still_unsupported_after_repairs_is_downgraded(run):
    run_testplan_doc(run, _llm(testplan_entries=clean_entries(always_wrong=True), claims_check=judge_ffh))
    stim = _section(run, "stimulus")
    wrong = next(e for e in stim["entries"] if "FFh" in e["text"])
    assert wrong["provenance"] == "ASSUMED" and "claims check" in wrong["validation"][-1]
    assert stim["claims_check"]["downgraded"] == 1 and len(stim["repair"]["refusals"]) == 2
    questions = _section(run, "questions")["entries"]
    assert any("7. Stimulus step could not be completed" in q["text"] for q in questions)
    assert "> Claims check:" in (run / "testplan_doc.md").read_text()


def test_failed_judge_does_not_block_the_section(run):
    def broken(payload):
        raise LLMError("transient", "simulated")
    run_testplan_doc(run, _llm(testplan_entries=clean_entries(), claims_check=broken))
    stim = _section(run, "stimulus")
    assert stim["status"] == "PASS" and stim["claims_check"]["status"] == "BLOCKED"
    assert all(e["provenance"] != "ASSUMED" or "claims check" not in " ".join(e["validation"]) for e in stim["entries"])


def test_judge_runs_only_after_deterministic_checks_and_not_where_disabled(run):
    llm = _llm()  # default fake entries fail deterministic checks in every section
    run_testplan_doc(run, llm)
    assert _section(run, "stimulus")["claims_check"]["status"] == "NOT_RUN"
    assert _section(run, "assumptions")["claims_check"]["status"] == "DISABLED"
    assert _section(run, "questions")["claims_check"]["status"] == "DISABLED"


def test_configuration_legal_values_are_judged(run):
    def judge_config(payload):
        return {"judgements": [{"id": c["id"], "supported": "legal values: 0, 1" not in c["claim"],
                                "reason": "values not stated"} for c in payload["claims"]]}
    def clean_configs(payload):
        return {"configurations": [
            {"field_id": f["field_id"], "randomize": True, "legal_values": ["0", "1"], "distribution": "uniform",
             "constraints": [], "reserved_handling": "", "notes": "", "provenance": "INFERRED",
             "cited_req_ids": [], "cited_chunk_ids": []} for f in payload["configurable_fields"]]}
    run_testplan_doc(run, _llm(testplan_entries=clean_entries(), testplan_configurations=clean_configs,
                               claims_check=judge_config))
    conf = _section(run, "configurations")
    assert any("claims check" in p for r in conf["repair"]["refusals"] for p in r["problems"])
    assert conf["claims_check"]["downgraded"] >= 1


def test_assumed_entries_and_uncited_entries_are_not_claims(run):
    G = load_graph(run / GRAPH_FILE)
    chunk = next(n for n, d in G.nodes(data=True) if d.get("type") == "chunk")
    entries = [dict(text="a", provenance="ASSUMED", cited_req_ids=[], cited_chunk_ids=[chunk], details=[]),
               dict(text="b", provenance="INFERRED", cited_req_ids=[], cited_chunk_ids=[], details=[]),
               dict(text="c", provenance="INFERRED", cited_req_ids=[], cited_chunk_ids=[chunk], details=["d1"])]
    claims = entry_claims(G, entries)
    assert [c["key"] for c in claims] == ["c"] and claims[0]["claim"] == "c Details: d1"
    assert claims[0]["sources"][0]["id"] == chunk
