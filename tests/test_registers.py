import json

import pytest

from dv_agent.cli import main
from dv_agent.graph.graph import load_graph
from dv_agent.core.llm import FakeLLM, LLMError
from dv_agent.pipeline import GRAPH_FILE, run_build_graph, run_ingest, run_registers
from dv_agent.plan.registers import (RegisterConfig, access_class, configurable_fields, extract_registers, parse_bits,
                                parse_number, register_questions)
from dv_agent.retrieval.retrieval import layered_view
from dv_agent.core.trace import Tracer
from dv_agent.plan.register_tables import table_records
from dv_agent.ingest.source_windows import extraction_windows

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
    run_build_graph(out, None, mode="graph")
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


def test_parallel_register_batches_preserve_verified_merge(graph, tmp_path):
    _, G = graph
    sequential = _extract(G, tmp_path, cfg=RegisterConfig(max_repairs=0))
    parallel = _extract(G, tmp_path, cfg=RegisterConfig(max_repairs=0, max_workers=2))
    assert parallel == sequential


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
    assert access_class("unknown") == "unknown"


def test_cli_registers_writes_outputs_and_reuses(graph, capsys, monkeypatch):
    out, _ = graph
    from dv_agent import cli
    monkeypatch.setattr(cli, "_llm", lambda: FakeLLM({"testplan_registers": handler}))
    assert main(["registers", "--out", str(out)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["reused"] is False and [r["abbreviation"] for r in first["registers"]] == ["CTRL", "STAT"]
    assert "### CTRL (CTRL) ✅<!--dv-evidence:" in (out / "registers.md").read_text()
    assert main(["registers", "--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["reused"] is True
    other = FakeLLM({"testplan_registers": handler})
    other.model = "other"
    assert run_registers(out, other, mode="graph")["reused"] is False


TABLE = """# Register map
Name Address Width Access Description
Payload 0 8 W FIFO data
Timing Control
Register (TCR)
4 16 RW Select the sampling period
Status 4 8 R Read-only flags
"""


def _table_graph(tmp_path):
    repo = tmp_path / "device"
    (repo / "doc").mkdir(parents=True)
    (repo / "doc" / "spec.md").write_text(TABLE)
    out = tmp_path / "table-run"
    run_ingest(repo, out)
    run_build_graph(out, None, mode="graph")
    return load_graph(out / GRAPH_FILE)


def test_explicit_inventory_survives_all_model_failures(tmp_path):
    G = _table_graph(tmp_path)
    def fail(payload):
        raise LLMError("incomplete", "output budget exhausted")
    result = _extract(G, tmp_path, fail)
    assert result["status"] == "BLOCKED"
    assert [(r["name"], r["address"], r["width"], r["access"]) for r in result["registers"]] == [
        ("Payload", "0", "8", "W"), ("Status", "4", "8", "R"),
        ("Timing Control Register (TCR)", "4", "16", "RW")]
    assert all(s["quote"] in G.nodes[s["chunk_id"]]["text"] for r in result["registers"] for s in r["sources"])
    assert result["configurable"] == []  # Never pretend missing fields are safe whole-register controls.
    assert "output budget exhausted" in result["failed_batches"][0]["detail"]


def test_llm_identifies_configuration_controls_and_excludes_payload(tmp_path):
    G = _table_graph(tmp_path)
    def identify(payload):
        records = []
        for c in payload["chunks"]:
            for r in table_records(c):
                r |= dict(configurable=r["name"] != "Payload" and r["access"] == "RW",
                          configuration_reason="Sampling period control" if r["access"] == "RW" else "Data/status",
                          configuration_quote=r["quote"])
                if r["access"] == "RW":
                    r["name"] = "Timing Control Register"
                records.append(r)
        return {"registers": records}
    result = _extract(G, tmp_path, identify)
    assert len(result["registers"]) == 3  # Full name and documented acronym merged; same address stays distinct.
    assert [f["register"] for f in result["configurable"]] == ["TCR"]
    field = result["configurable"][0]
    assert field["identification"] == "LLM" and field["review_status"] == "NEEDS_REVIEW"
    assert field["configuration_reason"] == "Sampling period control"


def test_extraction_windows_keep_the_end_of_long_source(tmp_path):
    text = "A source line\n" * 300 + "TAIL_CONTROL 0x10 RW"
    windows = extraction_windows([dict(text=text, chunk_id="CH-long")], 512)
    assert all(len(w["text"]) <= 512 for w in windows)
    assert windows[-1]["text"].endswith("TAIL_CONTROL 0x10 RW")
    covered = set()
    for w in windows:
        assert text[w["window_start"]:w["window_end"]] == w["text"]
        covered.update(range(w["window_start"], w["window_end"]))
    assert len(covered) == len(text)


def test_register_batch_default_is_one_complete_source_window(graph, tmp_path):
    _, G = graph
    seen = []
    def capture(payload):
        seen.extend(payload["chunks"])
        assert len(payload["chunks"]) == 1
        return {"registers": []}
    _extract(G, tmp_path, capture)
    assert {c["chunk_id"] for c in seen} == {n for n, d in G.nodes(data=True) if d["type"] == "chunk"}


def test_register_table_markdown_and_unrelated_bit_table():
    rows = table_records(dict(chunk_id="c", text="""Name | Address | Width | Access | Description
--- | --- | --- | --- | ---
CTRL | 0x04 | 16 | R/W | Select mode

Bit # Access Description
0 RW Enable
"""))
    assert len(rows) == 1 and rows[0]["address"] == "0x04" and rows[0]["access"] == "R/W"


def test_configuration_identification_requires_source_quote(graph, tmp_path):
    from dv_agent.plan.registers import record_problems
    _, G = graph
    cid = next(n for n, d in G.nodes(data=True) if d["type"] == "chunk" and "Register list" in d["text"])
    raw = handler({"chunks": [{"chunk_id": cid, "text": G.nodes[cid]["text"]}]})["registers"][0]
    raw |= dict(configurable=True, configuration_reason="Mode control", configuration_quote="invented evidence")
    assert any("configuration classification" in p for p in record_problems(G, {"registers": [raw]}, {cid}))


def test_register_cache_from_before_configuration_identification_is_not_reused(graph):
    out, _ = graph
    llm = FakeLLM({"testplan_registers": handler})
    run_registers(out, llm, mode="graph")
    path = out / "registers.json"
    result = json.loads(path.read_text())
    result.pop("extraction_signature")
    path.write_text(json.dumps(result))
    assert run_registers(out, llm, mode="graph")["reused"] is False


def test_register_chunks_slim_returns_cited_chunks(spec_repo, tmp_path):
    from dv_agent.graph.graph import build_structure
    from dv_agent.ingest.ingest import load_chunks, load_manifest
    from dv_agent.pipeline import run_ingest
    from dv_agent.plan.registers import register_chunks
    from dv_agent.retrieval.slim_index import build_index

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    G = build_structure(load_manifest(out), load_chunks(out))
    chunks = register_chunks(G, layered_view(G), "tmr32", RegisterConfig(), slim=build_index(out))
    assert chunks and any(c.get("source") == "slim" for c in chunks)
    assert all({"chunk_id", "text", "score", "doc_path", "pages"} <= set(c) for c in chunks)


def test_registers_basic_mode_marks_and_reuses(spec_repo, tmp_path):
    import json

    from dv_agent.pipeline import run_build_graph, run_ingest, run_registers
    from test_testplan_doc import _llm

    out = tmp_path / "run"
    run_ingest(spec_repo, out)
    run_build_graph(out, _llm(), mode="basic")
    first = run_registers(out, _llm(), mode="basic")
    assert first["status"] == "PASS" and first["reused"] is False
    assert json.loads((out / "registers.json").read_text())["mode"] == "basic"
    assert run_registers(out, _llm(), mode="basic")["reused"] is True
    assert run_registers(out, _llm(), mode="graph")["reused"] is False


def test_register_sources_use_document_markers(graph, tmp_path):
    from dv_agent.plan.registers import render
    _, G = graph
    md = "\n".join(render(_extract(G, tmp_path), "Register Map"))
    assert "📄<!--dv-sources:" in md
    detail = next(line for line in md.splitlines() if line.startswith("### CTRL "))
    assert "📄<!--dv-sources:" in detail
    field_row = next(line for line in md.splitlines() if line.startswith("| 7-4 |"))
    assert "📄<!--dv-sources:" in field_row
    conflict = next(line for line in md.splitlines() if line.startswith("> Conflict"))
    assert "📄<!--dv-sources:" in conflict
