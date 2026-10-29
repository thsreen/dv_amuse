"""Static relationships are exercised across instances, domains and verified RTL excerpts."""
import json
from pathlib import Path

import networkx as nx
import pytest

from rtl_agent.cli import main
from rtl_agent.dense import build_index, dense_scores, make_index
from rtl_agent.graph import BuildConfig, build_graph, graph_data, load_graph, save_graph
from rtl_agent.retrieval import QueryConfig, fetch_context, verified_excerpt
from rtl_agent.source import RTLExtractionError

DESIGN = """module lane #(parameter W=8)(input clk, rst_n, en,
    input [W-1:0] d, output logic [W-1:0] q);
always_ff @(posedge clk or negedge rst_n) begin
  if (!rst_n) q <= 0;
  else if (en) q <= d;
end
endmodule
module stage(input clk, rst_n, en, input [3:0] d, output [3:0] out);
lane #(.W(4)) u0(.clk(clk), .rst_n(rst_n), .en(en), .d(d), .q(out));
endmodule
module top(input clk_a, clk_b, rst_n, en, input [3:0] d,
           output [3:0] q_a, output [7:0] q_b);
stage left(.clk(clk_a), .rst_n(rst_n), .en(en), .d(d), .out(q_a));
lane right(clk_b, rst_n, 1'b1, q_a, q_b);
endmodule
"""


@pytest.fixture
def design(tmp_path):
    path = tmp_path / "design.sv"
    path.write_text(DESIGN)
    return path


@pytest.fixture
def graph(design):
    return build_graph([design], "top", features={"Capture": {"description": "Capture path", "targets": ["top.left.u0.q"]}})


def test_hierarchy_is_scoped_and_parameter_bindings_are_resolved(graph):
    G = graph
    assert G.has_edge("INST:top.left.u0", "MOD:lane", "INSTANCE_OF")
    assert G.has_edge("INST:top.right", "MOD:lane", "INSTANCE_OF")
    assert G.nodes["PAR:top.left.u0.W"]["value"] == 4
    assert G.nodes["PAR:top.right.W"]["value"] == 8
    assert G.has_edge("SIG:top.left.u0.d", "SIG:top.left.d", "PORT_DEPENDS_ON")
    assert G.has_edge("SIG:top.q_a", "SIG:top.left.out", "PORT_DEPENDS_ON")
    assert G.has_edge("SIG:top.right.q", "SIG:top.right.d", "DATA_DEPENDS_ON")
    assert not G.has_edge("SIG:top.left.u0.q", "SIG:top.right.d", "DATA_DEPENDS_ON")
    assert G.graph["analysis_status"] == "PASS"


def test_clock_and_async_reset_propagate_through_hierarchy(graph):
    G = graph
    clock = G.edges["SIG:top.left.u0.q", "SIG:top.left.u0.clk", "CLOCKED_BY"]
    reset = G.edges["SIG:top.left.u0.q", "SIG:top.left.u0.rst_n", "RESET_BY"]
    assert clock["edge"] == "posedge" and clock["root_signal"] == "SIG:top.clk_a"
    assert reset["active"] == "low" and reset["mode"] == "asynchronous"
    assert reset["root_signal"] == "SIG:top.rst_n" and reset["status"] == "INFERRED"
    assert G.edges["SIG:top.right.q", "SIG:top.right.clk", "CLOCKED_BY"]["root_signal"] == "SIG:top.clk_b"
    crossing = next(c for c in G.graph["domain_crossings"] if c["target"] == "SIG:top.right.q")
    assert crossing["source"] == "SIG:top.left.u0.q" and crossing["status"] == "NEEDS_REVIEW"


def test_reset_roles_come_from_behavior_not_names(tmp_path):
    p = tmp_path / "odd.sv"
    p.write_text("""module odd(input tick, clear, d, output reg q);
    always @(posedge tick) if (clear) q <= 0; else q <= d;
    endmodule""")
    G = build_graph([p], "odd")
    assert G.edges["SIG:odd.q", "SIG:odd.clear", "RESET_BY"]["mode"] == "synchronous"
    assert G.edges["SIG:odd.q", "SIG:odd.tick", "CLOCKED_BY"]["edge"] == "posedge"
    p.write_text("""module odd(input tick, clear, d, output reg q);
    always @(posedge tick or posedge clear) if (clear) q <= d; else q <= 1;
    endmodule""")
    G = build_graph([p], "odd")
    assert not any(k in ("RESET_BY", "CLOCKED_BY") for _, _, k in G.edges(keys=True))
    assert any("ambiguous" in d["reason"] for d in G.graph["diagnostics"])


def test_case_control_dependencies_and_lhs_indices_are_not_writes(tmp_path):
    p = tmp_path / "mux.sv"
    p.write_text("""module mux(input sel, idx, a, b, output reg y);
    reg mem [0:1];
    always_comb begin
      case (sel) 0: y = a; default: y = b; endcase
      mem[idx] = y;
    end
    endmodule""")
    G = build_graph([p], "mux")
    assert G.has_edge("SIG:mux.y", "SIG:mux.sel", "CONTROL_DEPENDS_ON")
    assert G.has_edge("SIG:mux.y", "SIG:mux.a", "DATA_DEPENDS_ON")
    assert G.has_edge("SIG:mux.y", "SIG:mux.b", "DATA_DEPENDS_ON")
    assert G.has_edge("SIG:mux.mem", "SIG:mux.idx", "DATA_DEPENDS_ON")
    assert not any(v == "SIG:mux.idx" and k == "WRITES" for _, v, k in G.edges(keys=True))


def test_missing_module_generate_and_functions_are_explicit_gaps(tmp_path):
    p = tmp_path / "partial.sv"
    p.write_text("""module partial(input clk, output q);
    external leaf(.clk(clk), .q(q));
    generate if (1) begin reg hidden; end endgenerate
    function automatic f(input fake); f=fake; endfunction
    endmodule""")
    G = build_graph([p], "partial")
    reasons = [d["reason"] for d in G.graph["diagnostics"]]
    assert G.graph["analysis_status"] == "PARTIAL"
    assert any("missing module" in r for r in reasons) and any("generate" in r for r in reasons)
    assert "SIG:partial.fake" not in G and "SIG:partial.hidden" not in G


def test_every_fact_and_excerpt_has_source_provenance(graph):
    G = graph
    for n, d in G.nodes(data=True):
        if d["type"] == "excerpt":
            record = verified_excerpt(G, n)
            assert record is not None
            raw = Path(record["path"]).read_bytes().decode()
            assert raw[record["char_start"]:record["char_end"]] == record["text"]
    for _, _, k, d in G.edges(keys=True, data=True):
        if k != "MEMBER_OF":
            assert d["evidence"] and all(verified_excerpt(G, cid) for cid in d["evidence"])


def test_graph_round_trip_and_rebuild_are_deterministic(graph, design, tmp_path):
    path = tmp_path / "graph.json"
    save_graph(graph, path)
    assert graph_data(load_graph(path)) == graph_data(graph)
    other = build_graph([design], "top", features={"Capture": {"description": "Capture path", "targets": ["top.left.u0.q"]}})
    assert graph_data(graph) == graph_data(other)


def test_context_combines_sources_and_traces_domains(graph):
    cfg = QueryConfig(top_k=24, hops=6)
    result = fetch_context(graph, "top.right.q clock reset Capture", cfg=cfg)
    assert result == fetch_context(graph, "top.right.q clock reset Capture", cfg=cfg)
    assert result["retrieval"]["pagerank"] == "PASS"
    assert sum(v > 0 for v in result["retrieval"]["sources"].values()) >= 4
    assert any(n["id"] == "SIG:top.right.q" for n in result["nodes"])
    assert any(f["relation"] == "RESET_BY" for f in result["facts"])
    assert all(f["evidence"] for f in result["facts"])
    known = {e["id"] for e in result["evidence"]}
    assert all(set(f["evidence"]) <= known for f in result["facts"])
    assert all(len(p["nodes"]) - 1 <= cfg.hops for p in result["paths"])
    assert result["domains"]


def test_scope_does_not_expand_into_other_instances(graph):
    result = fetch_context(graph, "q clock reset", scope="top.left", cfg=QueryConfig(top_k=30, hops=6))
    assert all(n.get("scope", "").startswith("top.left") or n["type"] in ("module", "feature") for n in result["nodes"])
    assert not any("top.right" in n["label"] for n in result["nodes"])
    assert all("top.right" not in c["summary"] for c in result["navigation"])
    with pytest.raises(RTLExtractionError, match="unknown RTL scope"):
        fetch_context(graph, "q", scope="top.missing")


def test_limits_unknown_query_and_corrupt_citation(graph):
    result = fetch_context(graph, "zzzz_not_in_design")
    assert result["nodes"] == [] and result["evidence"] == []
    for n, d in graph.nodes(data=True):
        if d["type"] == "excerpt":
            d["text_sha256"] = "invalid"
    result = fetch_context(graph, "top.right.q", cfg=QueryConfig(top_k=4, max_expansions=6, max_chars=500))
    assert len(result["nodes"]) <= 4 and result["retrieval"]["expansions"] <= 6
    assert result["evidence"] == [] and result["facts"] == []
    assert result["retrieval"]["rejected_excerpts"]


def test_embeddings_are_opt_in_and_bound_to_graph_and_model(graph):
    ids = ["SIG:top.left.u0.q", "SIG:top.right.q"]
    index = make_index(graph, "test-model", {ids[0]: [1, 0], ids[1]: [0, 1]})
    scores = dense_scores(graph, index, [0, 1], model="test-model")
    assert scores[ids[1]] == 1 and scores[ids[0]] == 0
    result = fetch_context(graph, "unseen_phrase", dense=scores)
    assert result["retrieval"]["dense"] == "PASS"
    assert any(n["id"] == ids[1] for n in result["nodes"])
    with pytest.raises(RTLExtractionError, match="model mismatch"):
        dense_scores(graph, index, [0, 1], model="different")
    graph.nodes[ids[0]]["label"] += " changed"
    with pytest.raises(RTLExtractionError, match="graph/model mismatch"):
        dense_scores(graph, index, [0, 1], model="test-model")


def test_embedding_provider_batches_and_budgets(graph):
    class Provider:
        model = "fake-offline"
        batches = []

        def embed(self, texts):
            self.batches.append(texts)
            return [[1., 0.] for _ in texts]

    provider = Provider()
    index = build_index(graph, provider, batch_size=3)
    assert all(len(b) <= 3 for b in provider.batches) and index["dimension"] == 2
    with pytest.raises(RTLExtractionError, match="nonfinite"):
        make_index(graph, "model", {"SIG:top.right.q": [float("nan"), 1]})


def test_graph_build_budget_and_bad_features(design):
    with pytest.raises(RTLExtractionError, match="budget"):
        build_graph([design], "top", cfg=BuildConfig(max_instances=1))
    with pytest.raises(RTLExtractionError, match="unknown targets"):
        build_graph([design], "top", features={"feature": {"targets": ["top.nope"]}})
    with pytest.raises(RTLExtractionError, match="positive"):
        QueryConfig(top_k=0)


def test_graph_cli_and_source_write_protection(design, tmp_path, capsys):
    out = tmp_path / "graph"
    assert main(["build-graph", str(design), "--top", "top", "--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["statistics"]["instances"] == 4
    graph_path = out / "rtl_graph.json"
    context = out / "context.json"
    assert main(["context", "top.right.q clock reset", "--graph", str(graph_path), "--save", str(context)]) == 0
    assert json.loads(capsys.readouterr().out)["evidence"] and context.is_file()
    assert main(["query", "q", "--graph", str(graph_path), "--save", str(design)]) == 2
    assert "overwrite source" in capsys.readouterr().err and design.read_text() == DESIGN
    assert main(["graph-info", "--graph", str(graph_path)]) == 0
    assert json.loads(capsys.readouterr().out)["domains"]


def test_wire_and_variable_initializers_are_not_confused(tmp_path):
    path = tmp_path / "init.sv"
    path.write_text("""module init(input d, output q);
      wire alias_d = d;
      reg storage = 0;
      assign q = alias_d;
    endmodule""")
    G = build_graph([path], "init")
    assert G.has_edge("SIG:init.alias_d", "SIG:init.d", "DATA_DEPENDS_ON")
    assert G.has_edge("SIG:init.alias_d", "SIG:init.d", "ALIASES")
    writer = next(u for u, v, k in G.in_edges("SIG:init.storage", keys=True) if k == "WRITES")
    assert G.nodes[writer]["process_kind"] == "declaration_init"
    assert not any(k == "RESET_BY" for _, _, k in G.edges(keys=True))


def test_wildcard_connections_and_active_preprocessor_variant(tmp_path):
    path = tmp_path / "variant.sv"
    path.write_text("""module leaf(input clk, input d, output q); assign q=d; endmodule
    module top(input clk, d, output q);
    `ifdef ENABLE
      leaf u0(.*);
    `else
      assign q=d;
    `endif
    endmodule""")
    disabled = build_graph([path], "top")
    enabled = build_graph([path], "top", defines={"ENABLE": "1"})
    assert "INST:top.u0" not in disabled and "INST:top.u0" in enabled
    assert enabled.has_edge("SIG:top.u0.d", "SIG:top.d", "PORT_DEPENDS_ON")


@pytest.mark.parametrize("text, error", [
    ("module top(input d); top recursive(.d(d)); endmodule", "recursive"),
    ("module a(input d, output q); endmodule module top(input d, output q); a u(d,.q(q)); endmodule", "mixed"),
])
def test_unsupported_hierarchy_is_not_silently_connected(tmp_path, text, error):
    path = tmp_path / "bad.sv"
    path.write_text(text)
    with pytest.raises(RTLExtractionError, match=error):
        build_graph([path], "top")


def test_local_parameters_cannot_be_overridden(tmp_path):
    path = tmp_path / "params.sv"
    path.write_text("module top(input a); localparam L=4; endmodule")
    with pytest.raises(RTLExtractionError, match="unknown top parameter"):
        build_graph([path], "top", overrides={"L": "8"})


def test_dense_cli_and_feature_annotation_query(design, tmp_path, capsys):
    out = tmp_path / "run"
    assert main(["build-graph", str(design), "--top", "top", "--out", str(out)]) == 0
    capsys.readouterr()
    graph_path = out / "rtl_graph.json"
    embeddings = tmp_path / "vectors.json"
    embeddings.write_text(json.dumps(dict(model="fake", vectors={"SIG:top.right.q": [0., 1.]})))
    assert main(["index-graph", "--graph", str(graph_path), "--embeddings", str(embeddings), "--out", str(out)]) == 0
    capsys.readouterr()
    vector = tmp_path / "query.json"
    vector.write_text(json.dumps(dict(model="fake", vector=[0., 1.])))
    assert main(["query", "unseen", "--graph", str(graph_path), "--dense-index", str(out / "rtl_dense_index.json"),
                 "--query-vector", str(vector)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["retrieval"]["dense"] == "PASS" and result["evidence"]
    assert main(["query", "q", "--graph", str(graph_path), "--query-vector", str(vector)]) == 2
    assert "supplied together" in capsys.readouterr().err


def test_implicit_net_dependencies_do_not_depend_on_source_order(tmp_path):
    path = tmp_path / "implicit.sv"
    path.write_text("module top(input a, output q); assign q=hidden; assign hidden=a; endmodule")
    G = build_graph([path], "top")
    assert G.has_edge("SIG:top.q", "SIG:top.hidden", "DATA_DEPENDS_ON")
    assert G.has_edge("SIG:top.hidden", "SIG:top.a", "DATA_DEPENDS_ON")
    assert any("implicit signal" in d["reason"] for d in G.graph["diagnostics"])


def test_local_shadowing_is_reported_without_writing_global_signal(tmp_path):
    path = tmp_path / "shadow.sv"
    path.write_text("""module top(input d, output reg q);
      initial begin reg q; q=d; end
    endmodule""")
    G = build_graph([path], "top")
    assert not G.has_edge("SIG:top.q", "SIG:top.d", "DATA_DEPENDS_ON")
    assert any("shadowing" in d["reason"] for d in G.graph["diagnostics"])


def test_sized_parameter_arithmetic_is_symbolic_instead_of_python_sized_math(tmp_path):
    path = tmp_path / "sized.sv"
    path.write_text("module top #(parameter N=4'b1111, P=N*N)(input d); endmodule")
    G = build_graph([path], "top")
    assert G.nodes["PAR:top.N"]["value"] == 15
    assert G.nodes["PAR:top.P"]["value"] is None
    assert any("parameter left symbolic" in d["reason"] for d in G.graph["diagnostics"])
