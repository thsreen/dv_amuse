# RTL-derived specification draft

The [RTL specification template](../src/rtl_agent/templates/rtl_specification_v0.json) follows the UART reference document's broad order: Introduction, IO Ports, Clocks, Registers, Operation, and Architecture. It adds questions for RTL engineers. The headings are reusable; UART-specific behaviour is never copied into a new design.

Build a source-backed RTL graph, then draft the specification:

```bash
.venv/bin/python -m rtl_agent build-graph \
  ../baseline_repos/uart16550/rtl/verilog/*.v \
  --top uart_top --out runs/uart_rtl_graph
.venv/bin/python -m rtl_agent build-spec \
  --graph runs/uart_rtl_graph/rtl_graph.json --out runs/uart_rtl_spec
```

The command writes `rtl_derived_spec.json` and `doc/rtl_derived_spec.md`. Each claim is `INFERRED`, `NEEDS_REVIEW`, has an RTL engineer review owner, and cites exact graph excerpts with source file and line range. Static analysis can identify ports, clock/reset candidates, sequential state, output dependencies, hierarchy, and analysis gaps. It does **not** establish design intent or a complete software-visible register map; the draft asks the engineer to confirm addresses, access and reset values. A PARTIAL graph remains visible as PARTIAL.

In the interactive orchestrator, an RTL-only repository automatically selects the RTL-derived flow. A prompt explicitly asking for a specification from RTL also selects it when ordinary specification documents exist. The four commands remain `/plan`, `/code`, `/run`, `/regress`. `/plan` creates the draft first, ingests it with `RTL_INFERRED` source authority, and generates the usual JSON/Markdown/HTML testplan. The requirement graph marks extracted requirements `INFERRED`; plan entries, configurations, register entries and checks are downgraded to `INFERRED` with `NEEDS_REVIEW` before saving. The orchestrator checks that this authority survived. `/code` is blocked for the unvalidated draft because its documented-only policy has no approved source to use.

An RTL engineer must review and validate the draft before it can become an authoritative specification. There is currently no automatic approval or promotion command. A separately approved document can be ingested through the ordinary specification flow; the unvalidated generated draft and its existing plan never silently become documented evidence. Editing Markdown or pressing Render testplan does not change JSON provenance or review status.
