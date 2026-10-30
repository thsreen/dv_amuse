# Feature understanding, dependencies and pseudocode

`/code` now follows this order:

1. Read brief stimulus/check/coverage intentions and the high-level strategy.
2. Group related intentions into feature work packages and identify dependencies.
3. Retrieve relevant specification excerpts for each package and write its understanding
   and pseudocode. Complete **all** feature pseudocode before generating components.
4. Collate the understanding into one implementation approach and dependency order.
5. Build the shared foundation, translate each feature pseudocode into typed components,
   then assemble cohesive tests and virtual sequences.
6. Validate/review the combined contract, render reusable templates and compile.

The model no longer receives the entire testplan and specification in one design request.
Planning batches contain brief ideas; feature requests contain the selected intentions,
their dependency summaries and relevant excerpts. Full sources stay local for validation.
The high-level strategy may contain inferred implementation proposals; they guide the
approach but cannot establish expected DUT behavior. Executable expectations require
documented plan pointers, eligible source IDs and exact source quotations.

## Temporary working documents

Artifacts are under `<run>/code_work/<fingerprint>/`, indexed by
`<run>/code_work_manifest.json`:

| Artifact | Purpose |
| --- | --- |
| `DEPENDENCIES.md`, `dependencies.json` | Dependent features, reasons, independent features and generation waves |
| `<feature>.context.json` | Selected plan intentions, documented records, exact excerpt text and offsets |
| `<feature>.md`, `<feature>.pseudocode.json` | Understanding, preconditions, stimulus/check/coverage pseudocode, completion, questions and essential blockers |
| `<feature>.recovery.context.json` | Focused evidence fetch and feedback used for one incomplete-feature repair |
| `COLLATED_PSEUDOCODE.md`, `.json` | Overall implementation approach, shared setup and ordered feature composition, written before code |
| `foundation.json` | Shared bindings, configuration, agent contracts and supported register mirrors |
| `<feature>.fragment.json` | Typed feature components and mappings from pseudocode steps to components/questions |
| `COLLATED_UNDERSTANDING.md`, `collated_understanding.json` | Component index and final integration recipe |

These are reviewable intermediate documents, kept inside ignored run directories for
recovery and debugging. Completed API responses checkpoint independently. Input/policy
changes create a new work directory. Edited work documents are refused instead of
silently overwritten. Direct edits are not automatically executable instructions.

To create dependency/pseudocode documents without generating SystemVerilog:

```sh
.venv/bin/python -m dv_agent.cli plan-code \
  --out runs/orch-20261030T181215Z --llm on
```

This stops after validated collated pseudocode, with `PSEUDOCODE_READY_NEEDS_REVIEW`.
Each feature needs source-backed actionable steps for its assigned intention categories and
explicit bounded completion criteria. Questions alone cannot satisfy a feature. Questions
about nonessential details or final bindings may remain alongside supported symbolic algorithms;
`blockers` records essential gaps that prevent supported work. A missing final executable
foundation does not justify discarding otherwise supported planning steps.

An incomplete feature triggers one focused BM25 fetch using its blockers/questions and one
validation repair. Recovery ranks relevant windows ahead of original source-ID preference,
with the same record/excerpt bounds and exact-quote checks. If it remains incomplete, the
manifest is `BLOCKED`, diagnostics and rejected output are saved in `code_planning_issue.json`,
and foundation/code generation does not begin. Recovered issues are labeled `RECOVERED`.

Collation receives full steps, preconditions, completion criteria and questions, without
duplicating fact quotations. Larger inputs are collated in bounded hierarchical batches.
Shared setup, stimulus, checks/scoreboard and coverage approaches must all contain text;
an inapplicable area needs an explicit explanation. Empty sections receive one repair and
then block readiness. Feature inclusion and dependency ordering are checked at every level.
A later `/code` or `build-code` in the same run reuses matching
planning responses and continues into the foundation and feature implementations.
The orchestrator commands remain `/plan`, `/code`, `/run`, `/regress` (plus existing
session controls). No new terminal command is needed to get the intermediate documents.

## Dependencies and reliability

Every implementation intention must be assigned exactly once. Unknown references,
duplicate assignments and dependency cycles are refused. Large intention inventories
are grouped in bounded batches, then cross-batch dependencies are collated from the
short task descriptions. Dependencies are labeled inferred implementation ordering,
with reasons and `NEEDS_REVIEW`; they do not silently become specification facts.

Independence means no dependency path in this planning graph. It does **not** prove
safe concurrent DUT stimulus. Final tests still use explicit sequencer handles;
same-agent concurrency is refused, and uniquely owned dependent sequences require
their setup feature to occur earlier. Shared reusable sequences and semantic ordering
remain part of review. Generation currently proceeds serially through the dependency
waves; independence is documented without claiming parallel execution.

Each stimulus/check/coverage pseudocode step must map to an emitted component or an
explicit question. Missing mappings cannot pass translation. Namespaces, agent ownership,
widths, source authority, quoted evidence and actual component references are validated.
Unsupported FIFO/IRQ/FSM behavior is retained as questions, not generic placeholder code
presented as an implementation.

Specific coverage uses typed goals: observed transaction fields, masks/shifts, bins,
crosses and event/address filters. The renderer creates a separate subscriber class
per goal, connects it to the appropriate monitor, clones the observed transaction and
samples the covergroup. It does not sample driver intent or give coverage classes VIFs.
Unsupported stateful/banked sampling conditions require additional contracts or review.

Retrieval uses the existing local BM25 implementation over documented records and source
windows. A feature receives at most 16 documented records and 8 exact excerpts of up to
1600 characters each; foundation retrieval allows 24 records. Excerpts preserve source
IDs and offsets, and quotes are checked both within retrieved windows and the original
source. There is no raw RTL retrieval in these steps. `code_context.json` reports the
actual size/cache state of each small request. A 48k-character per-request guard catches
an individual oversized package rather than trying to pack the entire design into it.

The API stages retain the 150-second default timeout, shared transport recovery and one
bounded validation repair per stage. No live-model quality or runtime target is implied
by offline tests. Actual simulator validation of the reusable coverage subscribers is
separate from testing model-generated grouping and pseudocode, which require a connected
generation run and review.

Final independent review also works in bounded component batches, with shared interface
signatures and only their cited facts; repeated quotes are stored once. It does not
reintroduce a whole-specification request after feature generation.
