import json

import pytest

from dv_agent.cli import main
from dv_agent.graph import load_graph
from dv_agent.llm import FakeLLM, LLMError
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_registers
from dv_agent.registers import (RegisterConfig, access_class, configurable_fields, extract_registers, parse_bits,
                                parse_number, register_questions)
from dv_agent.retrieval import layered_view
from dv_agent.trace import Tracer

SPEC = """# 1 Register list
Name | Address | Access | Reset value
CTRL | 0x00 | RW | 00h
STAT | 0x04 | R | 00h

# 2 CTRL register
Bit # | Access | Description
7-4 | RW | Mode select
5 | RW | Overlap bit
0 | RW | Start
Reset Value: 01h
"""


def handler(payload):
    regs = []
    for c in payload["chunks"]:
        cid, text = c["chunk_id"], c["text"]
        if "Register list" in text:
            regs += [dict(name="CTRL", abbreviation="CTRL", address="0x00", width="", access="RW", reset_value="00h",
                          description="", availability="", quote="CTRL | 0x00 | RW | 00h", chunk_id=cid, fields=[]),
                     dict(name="STAT", abbreviation="STAT", address="0x04", width="", access="R", reset_value="00h",
                          description="", availability="", quote="STAT | 0x04 | R | 00h", chunk_id=cid, fields=[]),
                     dict(name="PHANTOM", abbreviation="PHM", address="0x08", width="", access="RW", reset_value="",
                          description="", availability="", quote="", chunk_id=cid, fields=[])]
        if "CTRL register" in text:
            regs.append(dict(name="CTRL", abbreviation="CTRL", address="", width="8", access="", reset_value="01h",
                             description="Control.", availability="", quote="Reset Value: 01h", chunk_id=cid, fields=[
                                 dict(bits="7-4", name="Mode select", access="RW", reset_value="", description="Mode",
                                      values=[dict(value="0000", meaning="idle")], quote="7-4 | RW | Mode select"),
                                 dict(bits="5", name="Overlap bit", access="RW", reset_value="", description="",
                                      values=[], quote="5 | RW | Overlap bit"),
                                 dict(bits="0", name="Start", access="RW", reset_value="", description="Start",
                                      values=[], quote="0 | RW | Start")]))
    return {"registers": regs}


@pytest.fixture
def graph(tmp_path):
    repo = tmp_path / "blk"
    (repo / "doc").mkdir(parents=True)
    (repo / "doc" / "spec.md").write_text(SPEC)
    out = tmp_path / "run"
    run_ingest(repo, out)
    run_build_graph(out, None)
    return out, load_graph(out / GRAPH_FILE)


def _extract(G, tmp_path, h=handler, cfg=None):
    with Tracer(tmp_path / "t.jsonl", "t") as tracer:
        return extract_registers(G, layered_view(G), FakeLLM({"testplan_registers": h}), tracer, cfg=cfg)


def test_merges_sources_and_records_conflicts_instead_of_choosing(graph, tmp_path):
    _, G = graph
    res = _extract(G, tmp_path)
    regs = {r["abbreviation"]: r for r in res["registers"]}
    assert set(regs) == {"CTRL", "STAT"}
    assert any("PHANTOM" in v and "dropped" in v for v in res["validation"])
    ctrl = regs["CTRL"]
    assert ctrl["address"] == "0x00" and ctrl["width"] == "8" and len(ctrl["sources"]) == 2
    assert ctrl["reset_value"] == "00h"
    assert {"register": "CTRL", "attribute": "reset_value"}.items() <= res["conflicts"][0].items()
    assert res["conflicts"][0]["values"] == ["00h", "01h"]
    assert [r["abbreviation"] for r in res["registers"]] == ["CTRL", "STAT"]  # sorted by address


def test_field_checks_overlap_and_undocumented_values(graph, tmp_path):
    _, G = graph
    res = _extract(G, tmp_path)
    assert any("fields 7-4 and 5 overlap" in v for v in res["validation"])
    ctrl = next(r for r in res["registers"] if r["abbreviation"] == "CTRL")
    mode = next(f for f in ctrl["fields"] if f["name"] == "Mode select")
    assert mode["range"] == (7, 4) and mode["provenance"] == "DOCUMENTED"
    assert mode["values"][0]["documented"] is False
    qs = register_questions(res)
    assert any("different reset_value values for CTRL" in q["text"] for q in qs)
    assert any("overlap" in q["text"] for q in qs)


def test_configurable_fields_come_from_access_codes(graph, tmp_path):
    _, G = graph
    res = _extract(G, tmp_path)
    conf = res["configurable"]
    assert [(c["register"], c["field"]) for c in conf] == [("CTRL", "Mode select"), ("CTRL", "Overlap bit"),
                                                           ("CTRL", "Start")]
    assert [c["field_id"] for c in conf] == ["CFG-001", "CFG-002", "CFG-003"]
    assert all(c["source_chunk_ids"] for c in conf)
    whole = configurable_fields([dict(name="DATA", abbreviation="", address="", access="W", reset_value="",
                                      description="", availability="", fields=[], sources=[{"chunk_id": "CH-x"}])])
    assert whole[0]["field"] == "(whole register)"


def test_failed_batch_marks_step_blocked_but_keeps_results(graph, tmp_path):
    _, G = graph

    def flaky(payload):
        if any("CTRL register" in c["text"] for c in payload["chunks"]):
            raise LLMError("transient", "simulated")
        return handler(payload)
    res = _extract(G, tmp_path, flaky, RegisterConfig(batch_size=1))
    assert res["status"] == "BLOCKED" and res["failed_batches"]
    assert {r["abbreviation"] for r in res["registers"]} == {"CTRL", "STAT"}


def test_parsers():
    assert [parse_number(x) for x in ("0x1F", "1Fh", "8'h1f", "'h10", "0b101", "12", "zz")] == [31, 31, 31, 16, 5, 12, None]
    assert [parse_bits(x) for x in ("7-6", "15:8", "[3:0]", "bit 3", "2..5", "abc")] == [(7, 6), (15, 8), (3, 0), (3, 3), (5, 2), None]
    assert [access_class(a) for a in ("RW", "R/W", "W", "W1C", "R", "RO", "")] == [
        "writable", "writable", "writable", "writable", "read_only", "read_only", "unknown"]


def test_cli_registers_writes_outputs_and_reuses(graph, capsys, monkeypatch):
    out, _ = graph
    from dv_agent import cli
    monkeypatch.setattr(cli, "_llm", lambda: FakeLLM({"testplan_registers": handler}))
    assert main(["registers", "--out", str(out)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["reused"] is False and [r["abbreviation"] for r in first["registers"]] == ["CTRL", "STAT"]
    assert "### CTRL (CTRL) [DOCUMENTED]" in (out / "registers.md").read_text()
    assert main(["registers", "--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["reused"] is True
    other = FakeLLM({"testplan_registers": handler})
    other.model = "other"
    assert run_registers(out, other)["reused"] is False
