"""RTL-derived specifications retain inferred authority through planning boundaries."""
import json
from pathlib import Path

import pytest

from dv_agent.graph.graph import load_graph as load_spec_graph
from dv_agent.core.llm import FakeLLM
from dv_agent.pipeline import run_build_graph, run_ingest
from dv_agent.plan.testplan_doc import enforce_source_authority, render_markdown
from orchestrator_agent.actions import build_code, documented_plan
from orchestrator_agent.flow import load_flow
from orchestrator_agent.guards import post_testplan_check
from orchestrator_agent import repl as terminal
from rtl_agent.graph import build_graph, save_graph
from rtl_agent.source import RTLExtractionError
from rtl_agent.specification import MARKER, build_specification


def _draft(tmp_path):
    source = tmp_path / "design.sv"
    source.write_text("""module top(input clk, rst_n, d, output reg q);
always @(posedge clk or negedge rst_n) if (!rst_n) q <= 0; else q <= d;
endmodule
""", encoding="utf-8")
    graph = tmp_path / "rtl_graph.json"
    save_graph(build_graph([source], "top"), graph)
    result = build_specification(graph, tmp_path / "derived")
    return source, graph, result


def test_uart_inspired_draft_is_cited_and_needs_review(tmp_path):
    source, graph, result = _draft(tmp_path)
    draft = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
    markdown = Path(result["markdown"]).read_text(encoding="utf-8")
    assert result["status"] == "NEEDS_REVIEW"
    assert markdown.startswith(MARKER)
    assert [s["id"] for s in draft["sections"]] == [
        "introduction", "io_ports", "clocks", "registers", "operation", "architecture", "questions"]
    claims = [c for s in draft["sections"] for c in s["claims"]]
    assert claims and all(c["provenance"] == "INFERRED" and c["review_status"] == "NEEDS_REVIEW"
                          for c in claims)
    assert any(c["evidence"] and c["evidence"][0]["path"] == str(source)
               for c in claims)
    assert "register map" in markdown.lower() and "unconfirmed" in markdown.lower()
    assert "top instantiates top" not in markdown
    assert graph.is_file() and source.is_file()
    source.write_text(source.read_text() + "// changed after graph build\n")
    with pytest.raises(RTLExtractionError, match="source changed"):
        build_specification(graph, tmp_path / "stale")


class _EnrichLLM:
    model = "fake"

    def __init__(self, pick):
        self.pick, self.calls = pick, []

    def structured(self, **kw):
        from dv_agent.core.llm import LLMResult
        self.calls.append(kw["name"])
        ids = [e["id"] for e in kw["payload"]["evidence"]]
        claims = [dict(text="q follows d on clk.", inference_reason="sampled in clocked process", evidence_ids=ids[:1]),
                  dict(text="invented", inference_reason="x", evidence_ids=["SRC:missing"])]
        return LLMResult(data={"claims": claims if self.pick else []}, model=self.model, response_id="r1")


def test_model_enrichment_keeps_only_cited_claims_inferred(tmp_path):
    _, graph, _ = _draft(tmp_path)
    llm = _EnrichLLM(True)
    result = build_specification(graph, tmp_path / "enriched", llm=llm)
    draft = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
    extra = [c for s in draft["sections"] for c in s["claims"] if c["kind"] == "model_observation"]
    assert llm.calls and extra
    assert all(c["provenance"] == "INFERRED" and c["review_status"] == "NEEDS_REVIEW" and c["evidence"]
               for c in extra)
    assert not any(c["text"] == "invented" for c in extra)


def test_ingest_and_plan_preserve_inferred_authority(tmp_path):
    _, _, result = _draft(tmp_path)
    out = tmp_path / "plan"
    summary = run_ingest(tmp_path / "derived", out, ["doc/rtl_derived_spec.md"])
    assert summary["source_authority"] == "RTL_INFERRED"
    quote = "The analyzed top module is top."
    def requirements(payload):
        items = ([dict(statement=quote, quote=quote, kind="functional", entities=[])]
                 if quote in payload["text"] else [])
        return dict(summary="", entities=[], requirements=items)
    run_build_graph(out, FakeLLM({"spec_requirements": requirements,
                                  "requirement_dependencies": lambda payload: {"dependencies": []}}), mode="graph")
    graph = load_spec_graph(out / "graph.json")
    assert graph.graph["source_authority"] == "RTL_INFERRED"
    assert [n["status"] for _, n in graph.nodes(data=True) if n["type"] == "requirement"] == ["INFERRED"]
    assert all(n["authority"] == "RTL_INFERRED" for _, n in graph.nodes(data=True)
               if n["type"] == "chunk")
    doc = {"sections": [{"generator": "title", "title": "Draft plan", "details": []},
                        {"generator": "entries", "id": "checks", "heading": "Checks", "status": "PASS",
                         "entries": [{"text": "q follows d", "kind": "check", "provenance": "DOCUMENTED",
                                      "cited_req_ids": ["REQ-1"], "cited_chunk_ids": [], "details": [],
                                      "validation": [], "status": "NOT_RUN"}]}],
           "registers": {"registers": [{"name": "Q", "provenance": "DOCUMENTED"}]}}
    enforce_source_authority(doc, graph.graph["source_authority"])
    entry = doc["sections"][1]["entries"][0]
    assert entry["provenance"] == "INFERRED" and entry["review_status"] == "NEEDS_REVIEW"
    assert doc["registers"]["registers"][0]["provenance"] == "INFERRED"
    assert "RTL-DERIVED" in render_markdown(doc)
    plan_path = tmp_path / "testplan_doc.json"
    plan_path.write_text(json.dumps(doc), encoding="utf-8")
    assert post_testplan_check(doc_path=plan_path, rtl_used=True,
                               expected_authority="RTL_INFERRED") == []
    filtered, policy = documented_plan(doc)
    assert policy["kept"] == 0 and not filtered["sections"][1]["entries"]
    doc["sections"][1]["entries"][0]["provenance"] = "DOCUMENTED"
    plan_path.write_text(json.dumps(doc), encoding="utf-8")
    assert any("DOCUMENTED provenance" in v for v in post_testplan_check(
        doc_path=plan_path, rtl_used=True, expected_authority="RTL_INFERRED"))
    draft_path = Path(result["markdown"])
    draft_path.write_text(draft_path.read_text().replace(MARKER, ""), encoding="utf-8")
    refreshed = run_ingest(tmp_path / "derived", out, ["doc/rtl_derived_spec.md"])
    assert refreshed["source_authority"] == "RTL_INFERRED" and not refreshed["reused"]


def test_orchestrator_has_rtl_only_flow_and_blocks_unvalidated_code(tmp_path):
    path = Path(__file__).resolve().parents[1] / "src/orchestrator_agent/flows/rtl_derived_testplan_flow.json"
    flow = load_flow(path)
    assert [s["tool"] for s in flow["steps"]] == [
        "rtl_extract", "rtl_build_graph", "rtl_build_spec", "dv_ingest", "dv_build_graph", "dv_testplan"]
    out = tmp_path / "run"
    (out / "dv").mkdir(parents=True)
    (out / "rtl").mkdir()
    (out / "dv" / "testplan_doc.json").write_text(json.dumps({"source_authority": "RTL_INFERRED"}))
    (out / "rtl" / "interface_definition.json").write_text("{}")
    with pytest.raises(ValueError, match="RTL engineer validation"):
        build_code(out, {})


def test_interactive_preview_and_offline_draft_for_rtl_only_repo(tmp_path, monkeypatch):
    source = tmp_path / "rtl_only" / "top.sv"
    source.parent.mkdir()
    source.write_text("module top(input clk, output q); assign q = clk; endmodule\n")
    monkeypatch.setattr(terminal, "_default_out", lambda: tmp_path / "run")
    prompts = iter([f"Make a plan for {source.parent}", "/plan"])
    def read(_):
        try:
            return next(prompts)
        except StopIteration:
            raise EOFError from None
    shown = []
    assert terminal.repl(input_fn=read, output_fn=shown.append, llm_mode="off") == 0
    preview = "\n".join(shown)
    assert "Draft a specification from the selected RTL using the generic template" in preview
    assert "All draft-derived checks remain INFERRED" in preview
    assert "ready: yes" in preview
    assert "The inferred specification draft is ready" in preview
    assert (tmp_path / "run" / "rtl_spec" / "doc" / "rtl_derived_spec.md").is_file()
    assert terminal._asks_for_rtl_spec("Convert RTL to specification")


def test_top_is_the_uninstantiated_module_not_a_name_guess(tmp_path):
    from orchestrator_agent.repo_intake import inspect_repo, pick_top
    leaf = "module fifo(input c); endmodule"
    # Top without a *_top name, a helper named like a top, and a commented-out instance.
    srcs = {"soc": "fifo f0(.c(c)); // other_top o(.c(c));\n", "fifo": leaf, "other_top": "wire x;"}
    assert pick_top(srcs)[0] == "soc"
    # A testbench that instantiates the design is the only root here: it is chosen only if nothing else.
    assert pick_top({"dut": "fifo u(.c(c));", "fifo": leaf, "dut_tb": "dut d(.c(c));"})[0] == "dut_tb"
    assert pick_top({"core": "fifo u (.c(c));", "fifo": leaf, "tb_core": "wire y;"})[0] == "core"
    # Several roots: widest hierarchy wins, then the user's hint, a top-style name, a matching file name.
    wide = {"alpha": "fifo u(.c(c)); fifo v(.c(c));", "beta": "wire z;", "fifo": leaf}
    assert pick_top({**wide, "gamma": "alpha a(.c(c));"})[0] == "gamma"
    twins = {"a": "fifo u(.c(c));", "b": "fifo v(.c(c));", "fifo": leaf}
    top, notes = pick_top(twins)
    assert top == "" and "ambiguous" in notes[0]
    named = {"chip_a": "fifo u(.c(c));", "chip_b": "fifo v(.c(c));", "fifo": leaf}
    assert pick_top(named, "make a plan for chip_b")[0] == "chip_b"
    assert pick_top({**twins, "chip_top": "fifo w(.c(c));"})[0] == "chip_top"
    assert pick_top(twins, files={"a": Path("x/other.v"), "b": Path("x/b.v")})[0] == "b"
    repo = tmp_path / "r"
    (repo / "rtl").mkdir(parents=True)
    (repo / "rtl" / "d.v").write_text("module soc(input c);\n fifo #(.W(2)) f0 (.c(c));\nendmodule\n"
                                      "module fifo(input c);\nendmodule\n")
    found = inspect_repo(repo)
    assert found["top"] == "soc" and found["top_file"].name == "d.v"
