# Feature understanding, dependencies and pseudocode

`/code` executes small units in this order:

1. Clock and reset: bound deterministically in small fixed steps (inventory, clock, reset, timing, render, validate) with no model call; the common clock and reset UVCs and the common agent and environment are copied from templates. See [Common clock and reset flow](COMMON_UVC_FLOW.md).
2. A missing binding (an unmatched clock port, an undocumented reset level) is one question to the owner, answered once.
3. Identify physical interface groups and classify each as protocol or utility infrastructure. Finish **all interface bases first**: port names, widths, directions, documented roles and SV declarations. Then assess the minimum required infrastructure and build only the selected ownership/protocol configuration, one group at a time. Functional monitor/driver/coverage implementation follows these base checkpoints.
4. Group remaining verification work by one interface or one feature, at most two related intention pointers per task.
5. Run a **dedicated dependency analysis**, even for one grouping batch. Record whether each dependency requires execution ordering, extending a base sequence, or typed `p_sequencer` configuration.
6. For each feature in dependency order: retrieve → understand/pseudocode → implement → validate → checkpoint. Finish that feature before starting the next. Completed dependency signatures are available for reuse.
7. Collate the actual completed algorithms and compose tests. Validate/review and publish the assembled sources.

Generation does **not** launch Xezim. `/run` and `/regress` compile and simulate later.
The standalone `build-code --compile` remains an explicit opt-in outside `/code`.

`CODE_EXECUTION_PLAN.md` in the run directory shows the ordered queue and current phase.
`code_work/<fingerprint>/execution_plan.json` records the common cycle, unit statuses and
whether this is planning or generation. A failed unit blocks its successors; completed
source documents and API checkpoints stay available for recovery. The clock/reset queue
exists before execution; interface and feature queues are expanded after discovery.

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
| `COLLATED_PSEUDOCODE.md`, `.json` | Overall implementation approach, shared setup and ordered feature composition, after incremental implementation |
| `foundation.json` | Shared bindings assembled from separately validated clock/reset/interface units |
| `common_binding.json`, `foundation_clock.implementation.json`, `foundation_reset.implementation.json` | The binding steps and the resulting clock and reset bindings with their cited facts |
| `interface_<id>.*` | Per-unit context, pseudocode, implementation contract and explanation |
| `units/clock/`, `units/reset/`, `units/<interface>/` | Checkpointed reusable UVC/interface sources during generation |
| `dependency_handling.json` | Dedicated pass: ordering, sequence extension or sequencer controls, with reasons and control names |
| `execution_plan.json` | Mutable execution queue, common cycle and unit progress |
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
planning responses and incrementally generates the unit and feature implementations. Planning-only mode
records resolved foundation contracts but writes no SystemVerilog; its checkpoints are labeled PLANNED.
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

## Reusing sequences and sequencer configuration

The dependency pass outputs `mechanism`: `ordering`, `sequence_extension`, or
`p_sequencer_config`, plus a reason and any required control names. These are implementation
choices, not new specification facts. Cycles and unknown task/interface references are refused.

`Sequence.extends` names a same-agent base sequence. The renderer orders bases before children
and invokes `super.body()` before the extension's operations. Integration recognizes inherited
setup, so it does not require executing the same base as a separate preceding test stage.
Cross-agent dependencies use ordered virtual-sequence composition, not cross-agent inheritance.

`CodePlan.sequencer_variables` declares typed, source-backed per-agent configuration fields.
`Sequence.controls` binds an operation index and its data/address/count/cycles field to a variable.
The sequence declares its typed `p_sequencer` and reads that field; per-test `sequencer_settings`
can assign values before the virtual sequence starts. Validation checks ownership, physical width,
positive bounded counts, unknown variables, inheritance cycles, and conflicting random data controls.
No arbitrary model-written p_sequencer/VIF code is inserted. Unimplemented dependency mechanisms
need explicit questions; all generated behavior still needs review and subsequent simulation.

## Infrastructure completion is separate from verification completion

Interface declarations and utility/sideband signals use a dedicated prompt and
`InfrastructurePlan`: understanding, required actions, completion, documented facts, questions
and essential blockers. This schema has no stimulus/check/coverage sections. It does not inherit
the functional-contract requirement for a runnable test or scoreboard comparison.

Profiles in `templates/codegen/infrastructure_profiles.json` declare required artifacts, completion
criteria and deferred work. Clock needs a supported scalar binding and bounded testbench clock
configuration; missing DUT sampling edge is deferred to protocol work. Reset still requires a
supported binding and documented active polarity. Utility profiles avoid invented protocol agents
or monitors. Essential missing bindings/ownership remain blockers; later functional questions do not.

Every interface gets a `base_interfaces/<id>_if.sv` declaration and a saved base contract before
any interface collateral is attempted. These base files are intermediate scaffolding, separate
from final role-based interfaces. Deferred questions stay in execution metadata and foundation
questions. Existing reusable clock/reset UVC library files are retained; no new functional clock
or reset monitor/scoreboard test is demanded from the model. Functional feature validation
continues to require supported algorithms, completion and source-backed expectations.

## Detailed per-interface decision and build process

After clock/reset and **all** interface scaffolds are saved, process one interface at a time:

1. Select the next interface and load its saved port/role scaffold.
2. Retrieve relevant source excerpts and documented plan items for that interface.
3. Ask the LLM what infrastructure is needed, without generating code yet.
4. Validate source references, the selected level, required ownership and optional coverage.
5. Save the decision, responsibilities, rationale and questions in `infrastructure_needs/<id>.json`.
6. If the scaffold is sufficient, retain it and skip collateral generation. Otherwise write a short infrastructure action plan for the selected level.
7. Generate only the selected components, validate that they match the decision, and checkpoint their contracts and source files.
8. Move to the next interface. After these decisions/builds, group functional features, analyze dependencies and implement the verification work.

| Selected level | Generated infrastructure |
| --- | --- |
| `scaffold_only` | Existing port/role declarations; no agent build request |
| `utility_config` | Source-supported ownership/tie-offs and configuration, with no protocol agent |
| `passive_agent` | Configuration and monitor container; no driver or sequencer |
| `full_agent` | Configuration, driver, sequencer, monitor and agent |

Builtin monitor-fed coverage is generated only when requested by the assessment. Later explicit
feature coverage goals remain separate. Decisions are inferred implementation choices requiring
review; their supporting DUT facts retain documented source lineage. Input ownership cannot be
omitted to make a scaffold-only decision pass. Passive observation also needs source-supported
input ownership wherever inputs are present. Architecture assessment has its own `assess` step
in `execution_plan.json` and the terminal dashboard. Xezim remains deferred.
