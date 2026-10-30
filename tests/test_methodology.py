"""Methodology rules: natural-language conditions without a spec source."""

import json

import networkx as nx
import pytest

from dv_agent.plan import methodology
from dv_agent.quality.claims import entry_claims
from dv_agent.report.provenance_badge import badge, decode
from dv_agent.plan.testplan_doc import (_badge, _entries_schema, _validate_entries,
                                        enforce_source_authority)
from dv_agent.uvm import build_uvm


_UVM_PORTS = [
    {"direction": "input", "width": 1, "name": "clk"},
    {"direction": "input", "width": 1, "name": "rst_n"},
    {"direction": "input", "width": 8, "name": "data"},
    {"direction": "output", "width": 1, "name": "ready"},
]


def _definition():
    return {"sources": ["top.sv"], "direction_reference": "DUT", "parameters": [],
            "ports": [dict(p) for p in _UVM_PORTS]}


def _rules():
    return methodology.load_methodology_rules()


def test_defaults_load_xprop_rule():
    rules = _rules()
    assert [r["id"] for r in rules] == ["METH-XPROP-1"]
    rule = rules[0]
    assert rule["enforced"] is True
    assert "uvm_error" in rule["statement"]
    assert "checks" in rule["applies_to"]


def test_user_file_merges_and_overrides(tmp_path):
    path = tmp_path / "mine.json"
    path.write_text(json.dumps({"rules": [
        {"id": "METH-XPROP-1", "statement": "Custom X rule text that is long enough here.",
         "applies_to": ["checks"], "kinds": ["protocol_check"], "enforced": False},
        {"id": "METH-CUSTOM-1", "statement": "Another custom rule with enough words in it.",
         "applies_to": ["coverage"], "kinds": ["cover_point"], "enforced": True}]}))
    rules = methodology.load_methodology_rules(path)
    assert [r["id"] for r in rules] == ["METH-XPROP-1", "METH-CUSTOM-1"]
    assert rules[0]["enforced"] is False
    assert rules[1]["applies_to"] == ["coverage"]


def test_invalid_rule_files_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"rules": [{"id": "nope", "statement": "long enough statement here yes",
                                          "applies_to": ["checks"], "kinds": ["k"]}]}))
    with pytest.raises(ValueError, match="METH"):
        methodology.load_methodology_rules(bad)
    dup = tmp_path / "dup.json"
    dup.write_text(json.dumps({"rules": [
        {"id": "METH-A-1", "statement": "long enough statement number one here",
         "applies_to": ["checks"], "kinds": ["k"]},
        {"id": "METH-A-1", "statement": "long enough statement number two here",
         "applies_to": ["checks"], "kinds": ["k"]}]}))
    with pytest.raises(ValueError, match="duplicate"):
        methodology.load_methodology_rules(dup)
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json")
    with pytest.raises(ValueError, match="invalid JSON"):
        methodology.load_methodology_rules(malformed)
    with pytest.raises(ValueError, match="missing.json"):
        methodology.load_methodology_rules(tmp_path / "missing.json")


def test_fingerprint_stable_and_sensitive():
    rules = _rules()
    assert methodology.rules_fingerprint(rules) == methodology.rules_fingerprint(rules)
    changed = [dict(rules[0], enforced=False)]
    assert methodology.rules_fingerprint(changed) != methodology.rules_fingerprint(rules)


def test_forced_entry_shape():
    entry = methodology.forced_entry(_rules()[0])
    assert entry["provenance"] == "DOCUMENTED"
    assert entry["inference_reason"] == "Recommended by DV agent"
    assert entry["cited_methodology_ids"] == ["METH-XPROP-1"]
    assert entry["cited_req_ids"] == [] and entry["cited_chunk_ids"] == []
    assert entry["quote"] in _rules()[0]["statement"]
    assert any("Recommended by DV agent (METH-XPROP-1)" in d for d in entry["details"])


def test_missing_enforced_detects_gaps():
    rules = _rules()
    assert methodology.missing_enforced([], rules, "checks") == ["METH-XPROP-1"]
    assert methodology.missing_enforced([], rules, "coverage") == []
    cited = [{"cited_methodology_ids": ["METH-XPROP-1"]}]
    assert methodology.missing_enforced(cited, rules, "checks") == []
    assert methodology.missing_enforced([{}], rules, "checks") == ["METH-XPROP-1"]


def test_claims_skip_methodology_only_entries():
    entries = [methodology.forced_entry(_rules()[0])]
    assert entry_claims(entries, {}, {}) == []


def test_schema_advertises_methodology_ids():
    schema = _entries_schema(["protocol_check"], ["REQ-1"], ["CH-1"],
                             meth_ids=["METH-XPROP-1"])
    item = schema["properties"]["entries"]["items"]
    assert "cited_methodology_ids" in item["required"]
    assert item["properties"]["cited_methodology_ids"]["items"]["enum"] == ["METH-XPROP-1"]
    plain = _entries_schema(["protocol_check"], ["REQ-1"], ["CH-1"])
    assert "cited_methodology_ids" not in plain["properties"]["entries"]["items"]["properties"]


def test_validation_keeps_documented_methodology_entry():
    rules = _rules()
    raw = [dict(text="Monitors error on X.", kind="protocol_check", provenance="DOCUMENTED",
                inference_reason="", cited_req_ids=[], cited_chunk_ids=[],
                cited_methodology_ids=["METH-XPROP-1", "METH-BOGUS"], details=[])]
    (entry,) = _validate_entries(nx.MultiDiGraph(), raw, set(), set(), 10, None, rules)
    assert entry["provenance"] == "DOCUMENTED"
    assert entry["cited_methodology_ids"] == ["METH-XPROP-1"]
    assert entry["inference_reason"] == "Recommended by DV agent"
    assert any("Recommended by DV agent (METH-XPROP-1)" in d for d in entry["details"])
    assert any("unknown methodology" in v for v in entry["validation"])


def test_slim_quote_comes_from_rule_statement():
    rules = _rules()
    span = rules[0]["statement"][10:60]
    raw = [dict(text="Monitors error on X.", kind="protocol_check", provenance="DOCUMENTED",
                inference_reason="", cited_req_ids=[], cited_chunk_ids=[],
                cited_methodology_ids=["METH-XPROP-1"], details=[], quote="  " + span + " ")]
    (entry,) = _validate_entries(nx.MultiDiGraph(), raw, set(), set(), 10, None, rules)
    assert entry["quote"] == span
    assert entry["validation"] == []


def test_rtl_authority_exempts_methodology_entries():
    doc = {"sections": [{"entries": [
        dict(text="M", kind="k", provenance="DOCUMENTED", cited_req_ids=[], cited_chunk_ids=[],
             cited_methodology_ids=["METH-XPROP-1"]),
        dict(text="S", kind="k", provenance="DOCUMENTED", cited_req_ids=["REQ-1"], cited_chunk_ids=[])]}]}
    enforce_source_authority(doc, "RTL_INFERRED")
    meth, spec = doc["sections"][0]["entries"]
    assert meth["provenance"] == "DOCUMENTED"
    assert "review_status" not in meth
    assert spec["provenance"] == "INFERRED"


def test_rendered_badge_cites_rule():
    entry = methodology.forced_entry(_rules()[0])
    md = _badge(entry)
    assert md.startswith("✅")
    info = decode(md.split("<!--dv-evidence:")[1].rstrip("-->"))
    assert info["citations"] == ["METH-XPROP-1"]
    assert info["reason"] == "Recommended by DV agent"


def test_monitor_errors_on_x_with_reset_gate():
    artifacts, _ = build_uvm(_definition(), prefix="demo", clock="clk", reset="rst_n",
                             reset_active="low")
    monitor = artifacts["uvm/demo_monitor.svh"]
    assert "METH-XPROP-1" in monitor
    assert 'if ($isunknown(cfg.vif.data)) `uvm_error("XPROP", "X/Z sampled on data");' in monitor
    assert "if (cfg.vif.rst_n != 1'b1) begin" in monitor
    assert 'if ($isunknown(cfg.vif.ready)) `uvm_error("XPROP", "X/Z sampled on ready");' in monitor
    assert "cfg.vif.clk)) `uvm_error" not in monitor


def test_monitor_errors_on_x_without_reset():
    no_reset = {"sources": ["top.sv"], "direction_reference": "DUT", "parameters": [],
                "ports": [p for p in _UVM_PORTS if p["name"] != "rst_n"]}
    artifacts, _ = build_uvm(no_reset, prefix="demo", clock="clk")
    monitor = artifacts["uvm/demo_monitor.svh"]
    assert 'if ($isunknown(cfg.vif.ready)) `uvm_error("XPROP", "X/Z sampled on ready");' in monitor
    assert "!= 1'b" not in monitor


def test_badge_keeps_reason_on_documented():
    md = badge("DOCUMENTED", ["METH-XPROP-1"], "Recommended by DV agent")
    assert md.startswith("✅")
    info = decode(md.split("<!--dv-evidence:")[1].rstrip("-->"))
    assert info["state"] == "DOCUMENTED"
    assert info["reason"] == "Recommended by DV agent"
    assert info["citations"] == ["METH-XPROP-1"]
