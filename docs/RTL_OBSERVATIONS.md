# Observations from RTL in the test plan

The template now contains **4. Observations from RTL**, before **5. High Level Verification Strategy**.
It supplements the specification-driven plan with implementation concerns requiring RTL design engineer
review. It does not change the authority for intended behavior, interface definitions or register values.

Build the RTL graph independently, then explicitly opt in:

```bash
.venv/bin/python -m rtl_agent build-graph ../baseline_repos/uart16550/rtl/verilog/*.v \
  --top uart_top --out runs/uart_rtl_graph

.venv/bin/dv-agent testplan --out runs/uart16550 \
  --rtl-graph runs/uart_rtl_graph/rtl_graph.json --rtl-scope uart_top
```

The same flags work with `dv-agent pipeline <spec-repository> --testplan`. Without `--rtl-graph`,
the section is `NOT_RUN`, no RTL graph is read and no RTL observation model calls occur. The remaining
sections retain the specification-driven behavior. Custom templates must place the observations
generator before strategy.

## What the model can fetch

The host first fetches a clock/reset/interconnection context. The model may then request up to two
focused graph queries in each of two rounds. The host runs these read-only queries through the RTL
combined fetcher, respecting the user-selected instance scope. A hierarchy inventory, possible crossings,
analysis diagnostics and the retrieved specification context help the model choose useful queries.

There is no model-selected workflow or arbitrary file/tool execution. The step order remains fixed.
Graph expansion, query count, source excerpts, prompt text and observation count have explicit caps.
Fetch queries/results and model/refusal calls are traced; token reporting includes these calls.

## Observation and review contract

Each observation records:

- The implementation consideration and category: clocking, reset, crossing, dependency, integration,
  feature control or analysis gap.
- Exact fetched RTL excerpt IDs and relevant instance/signal node IDs, with graph snapshot fingerprint,
  source paths, line/character locations and hashes retained for review.
- A specification comparison: `DOCUMENTED_IN_SPEC`, `NOT_FOUND_IN_RETRIEVED_SPEC`, or `POSSIBLE_CONFLICT`.
  Matches/conflicts require spec citations. No match in retrieved context is **not proof** that the
  full specification omits the handling.
- A proposed verification action and a concrete question for RTL design engineers.
- Fixed `INFERRED`, `NEEDS_REVIEW`, `review_owner: RTL_DESIGN_ENGINEER`, and `gap_status: UNCONFIRMED`.
  The model cannot approve its own findings or turn static crossings into verified bugs/safe circuits.

Code refuses unknown citations, missing source support and incomplete observations. A separate model
call judges whether cited graph/source evidence supports the observation. Unsupported output is sent
through bounded refuse-and-repair; unsupported leftovers are withheld. Graph analysis may be partial,
and findings are explicitly non-exhaustive. This check assists review; it is not designer sign-off.

## How observations drive the plan

Strategy receives accepted observations and must return a handling action for each, with assigned agents
or designer/integration handling. Missing actions cause repair feedback. These actions retain RTL review
status and cannot expand agent drive ownership beyond specification-defined interface groups.

Stimulus, checks, coverage, callouts and later sections receive the observation IDs and proposals.
Entries can cite `cited_rtl_observation_ids`; such entries are always inferred and review-required.
Checks must address each observation with a proposed check or explicit review-dependent handling.
Designer questions collect each observation's review question. The document records
`rtl_observation_coverage` to show strategy handling and the sections citing each observation.

The regular claims check sees cited implementation excerpts for these proposals while still requiring
specification support for intended/expected behavior. Legal register values remain specification-derived.
RTL citations remain separate from specification requirement/chunk IDs and spec coverage accounting.

`testplan_doc.json` retains fetched excerpts, graph facts, possible crossings, analysis gaps, queries,
repair summaries and review ownership. Markdown renders findings, proposed tests, source locations and
the review requirement. Test-plan reuse includes the RTL graph fingerprint/path and selected scope;
changed snapshots/scopes or removing the opt-in regenerate the result.

The flow is offline-tested with a fake model, including unknown source IDs, an exact source with an
unsupported CDC-safety claim, missing strategy handling and graph/scope cache invalidation. Live Meta
API behavior, actual CDC safety and designer acceptance remain unverified.
