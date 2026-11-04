# Silicon Copilot architecture

dv_agent turns a design repository's specification documents into a reviewed, traceable verification
test plan, using Meta's Muse Spark model for the semantic work and deterministic checks to keep it honest.

## System overview

Functional testplan-to-code contracts, reusable templates, monitor-fed coverage and
execution evidence are described in [CODE_GENERATION.md](CODE_GENERATION.md).

![Silicon Copilot end-to-end architecture](architecture/end_to_end.svg)

Three independent agents sit under one orchestrator. Specifications stay authoritative for intended
behavior; RTL contributes only wiring facts to generated code and review-required observations to the plan.
These diagrams show the architecture as designed. Recorded results and limitations are in the
[review pack guide](../review_artifacts/run_20261104_8bit_pass/README.md).

| Flow | Diagram | More |
|---|---|---|
| `/plan` orchestration | [plan_orchestration.svg](architecture/plan_orchestration.svg) | [ORCHESTRATOR.md](ORCHESTRATOR.md) |
| Inside the test plan | [testplan_sections.svg](architecture/testplan_sections.svg) | [below](#specification-pipeline) |
| Request selects the RTL configuration | [request_configuration.svg](architecture/request_configuration.svg) | [RTL_CONFIGURATION.md](RTL_CONFIGURATION.md) |
| `/code` stages | [code_generation.svg](architecture/code_generation.svg) | [CODE_WORK_PACKAGES.md](CODE_WORK_PACKAGES.md) |
| Contract to simulation | [code_to_simulation.svg](architecture/code_to_simulation.svg) | [CODE_GENERATION.md](CODE_GENERATION.md) |
| Generated testbench | [testbench_runtime.svg](architecture/testbench_runtime.svg) | [REGISTER_WRITE.md](REGISTER_WRITE.md) |

## Specification pipeline

dv_agent turns a design repository's specification documents into a reviewed, traceable verification
test plan, using Meta's Muse Spark model for the semantic work and deterministic checks to keep it honest.

![Inside the test plan](architecture/testplan_sections.svg)

The diagram shows the live basic-mode path; the graph stages in the table below run in graph mode. The opt-in [RTL observations extension](RTL_OBSERVATIONS.md) runs before strategy and does not change specification authority.

## Principles

| Principle | Where it is enforced |
|---|---|
| Specification-authoritative intended behavior; optional RTL implementation observations | Default ingestion still skips design sources. An explicit prebuilt RTL graph enables the dedicated review-required observations stage before strategy; see RTL_OBSERVATIONS.md |
| Fixed step order chosen by the user; the model never picks the next step | `pipeline.py`, `plan.testplan_doc.build_testplan_doc` |
| The model does the semantic work; code verifies it | Every model call goes through a schema and a check (below) |
| Checks outside the model refuse its output and the model repairs it | `quality.repair.structured_with_repair` |
| Specification conflicts are reported, never resolved silently | `plan.registers._merge`, designer questions |
| Every statement traces to an exact specification location | Chunk offsets, verbatim quotes, citation filters, graph lineage |
| Human review is authoritative | Everything is `NEEDS_REVIEW`; designer questions; sign-off command planned |

## Pipeline

| # | Stage | Modules | Model calls | Checks | Outputs |
|---|---|---|---|---|---|
| 1 | Ingest | `ingest.ingest` | none | discovery rules (format preference, skipped folders, changelogs); every skip has a reason | `manifest.json`, `text/`, `chunks.jsonl` |
| 2 | Graph build | `graph.graph`, `ingest.extract`, `graph.community`, `retrieval.dense` | `spec_requirements` per chunk; `requirement_dependencies` per entity group; optional embeddings; fetches may run on 1-4 workers | quotes located verbatim (whitespace and typography tolerant); dependency evidence quote must be in an endpoint's quote; entity references resolved by owner | `graph.json`, `build_stats.json`, `dense/` |
| 3 | Retrieval and fetch | `retrieval.retrieval`, `retrieval.graph_fetch`, `retrieval.combined_fetch`, `plan.testplan_context`, `plan.planning` | `rerank_chunks`, `test_plan_items` (per-requirement `plan` command) | evidence is always an L1 chunk; every item records its sources and path; citations limited to retrieved IDs | `query`, `context`, `deps`, `features` output; `test_plan.json` |
| 4a | Interfaces | `plan.interfaces` | `testplan_interfaces` | names and defining quotes in the cited chunk; direction, width and active level marked when not stated; one group per signal; groups sharing functionality and module type flagged | `interfaces.json/.md` |
| 4b | Register map | `plan.registers` | `testplan_registers` per batch of chunks | names, quotes, addresses, widths, access, reset values and encodings must be written in the chunk; records merged across chunks; conflicts and overlaps reported; writable fields from access codes | `registers.json/.md` |
| 4c | Verification strategy | `plan.strategy` | `testplan_strategy` | every interface group covered once; agents drive only DUT inputs of their groups; passive agents never drive; registers, scoreboard inputs and sequence agents must exist | `strategy.json/.md` |
| 5 | Test plan | `plan.testplan_doc`, `templates/*.json` | `testplan_entries` per text section; `testplan_configurations` | citations within the supplied evidence; DOCUMENTED/INFERRED need citations; every writable field configured; legal values stated in the specification | `testplan_doc.json/.md/.html` |
| 6 | Human review | (designer questions in section 11) | none | conflicts, gaps, undocumented signal properties and unresolved repairs raised as questions | sign-off command planned |

Step 4c reads the saved outputs of 4a and 4b (regenerating them only when missing or stale) and records
their trace IDs. Inside `testplan`, steps 4a-4c run in memory and feed sections 3-5; every section also
receives the interface groups and the earlier sections, so stimulus, checks and coverage reuse the
strategy's agent and sequence names.

## Combined graph fetch (stage 3)

Every fetch (`testplan_context.fetch_context`, used by all steps and sections) runs `combined_fetch.combined_fetch`:

| Source | What it adds |
|---|---|
| retrieval | BM25 + dense seeds fused, entity anchors as extra seeds, Personalized PageRank |
| entity | entities named in the topic (an owned name such as a field only with its owner); their parts and owners via `HAS_PART`, requirements mentioning them, sections, communities |
| dependency | transitive preconditions of the top requirements (`DEPENDS_ON`, `CONSTRAINS`, `REFINES`) |
| global | communities ranked by their summaries, expanded into member requirements |
| path | shortest weighted path from the topic's anchors and seeds to each verified interface signal, register and uncovered requirement; requirements and chunks on the path |
| coverage | requirements earlier sections have not cited directly |

Adaptive selection gives each source up to `min_per_source` of its best items, then fills by score up to
the cap; an item reached by several sources lists them all. Model-written sections also receive a
precondition-first `dependency_order` (cycles become designer questions), and Checks is refused until it
cites the requirements no earlier section covers. The document ends with a requirement coverage report.
`dv-agent deps REQ-...` prints closure, order, cycles and conflicts; `dv-agent context "<topic>" --global N`
shows the bundle with its paths and selection.

## Test-plan template

The template is data (`src/dv_agent/templates/testplan_quick_v0.json`): step blocks (`interfaces`,
`registers`) and sections, each with a `generator`, retrieval `queries` (with a `{scope}` placeholder)
and `instructions`. Generators: `title` (no model call), `register_map` (rendered from step 4b),
`strategy` (step 4c), `configurations`, and `entries` (free-text sections with `entry_kinds`,
`collect_assumed`, `include_conflicts`). A new template is a new JSON file; a new generator is needed
only for a new output shape.

## Refuse and repair

`quality.repair.structured_with_repair(llm, tracer, name, instructions, payload, schema, check)`:

1. The model answers in the step's JSON schema.
2. `check(answer)` returns the problems the model can fix; an empty list accepts the answer.
3. A refused answer goes back with `previous_output` and `refusal` (the problems) and repair instructions.
4. At most `DV_AGENT_MAX_REPAIRS` repairs (default 2). A failed repair call keeps the last answer.
5. In free-text sections and Configurations, once the deterministic checks pass, a separate `claims_check`
   call judges each DOCUMENTED/INFERRED claim against only its cited text. Unsupported
   claims are refused like any other problem; claims still unsupported after the budget become ASSUMED.

After the last attempt the step's deterministic cleanup still applies (drop, downgrade, fill), and the
unresolved problems become one designer question per step. Checks never include problems the
specification causes (for example two chunks giving different reset values). Each refusal is a
`refusal:<step>` trace span and appears in the Markdown. Not yet applied to stage 2 extraction.

## Model integration

`core.llm.MetaClient`: OpenAI Python SDK against `https://api.meta.ai/v1`, model `muse-spark-1.3`, Responses
API with `text.format` `json_schema` (Chat Completions with `META_API_STYLE=chat`). Bounded retries for
rate limits, timeouts and server errors; errors are classified without echoing request details.
Responses are cached by a hash of model, call name, instructions, payload and schema, so reruns cost
nothing unless a prompt changes. Each call records input, cached-input, output and reasoning tokens
(estimated when the API reports none); the final test plan lists them per model call, with repair and
local-cache counts, and `dv-agent usage` totals them per run and per call. `--llm auto|on|off` (or `DV_AGENT_LLM_MODE`) controls
whether the model is used; `FakeLLM` drives the offline tests. Live runs are recorded under `runs/`: `orch-20261030T181215Z` (basic mode, 34 API calls, 13 of 13 sections PASS, 2 token-budget retries) and `uart_fast` (graph mode, 61 calls, 21 repair calls, 11 of 12 sections PASS). The API accepted strict `json_schema` output in these runs. Per-attempt metadata (no
prompts, headers or provider bodies) is in each stage's `llm_requests.jsonl`.

## Provenance and lineage

```
specification file ─ chunk (offsets, page, SHA-256)
   └─ requirement / signal / register record (verbatim quote, DOCUMENTED)
        └─ dependency edge (evidence quote, INFERRED)
             └─ test-plan entry (tag + cited requirement and chunk IDs)
                  └─ section artifact (TPS-*), trace span with fact IDs
```

`graph.graph.attach_artifact` adds each generated section, the interface definitions and the register map as
graph nodes with `DERIVED_FROM` edges; `dv-agent lineage <id>` walks back to every requirement and chunk
behind it. `core.trace` writes one trace per run to `trace.jsonl` and mirrors it to Langfuse when keys are
set; a Langfuse failure disables the mirror without stopping the run.

## Around the pipeline

| Package | Role | Boundary |
|---|---|---|
| `orchestrator_agent` | Interactive `/plan`, `/code`, `/run`, `/regress` and an advanced flow-JSON CLI; live dashboard with stage progress | Flow order, budgets and never-do list come from JSON; the decider may revisit, skip or stop but budget exhaustion reverts to the owner. See `ORCHESTRATOR.md` |
| `rtl_agent` | RTL ports, hierarchy and data/control/clock/reset graph with cited retrieval | Independent of `dv_agent`; its prebuilt graph reaches the test plan only through the opt-in observations stage |
| UVM scaffold and simulation | UVM build from cited DOCUMENTED plan items only; smoke test on local Xezim; ephemeral E2E nodes | RTL behavior facts never enter generated code; a missing simulator is BLOCKED, never PASS |
| Report viewer | Markdown is the editable source; HTML is rendered from it without a model call; loopback viewer with plan selector and provenance badges | Serves only catalogued plans; `render-testplan` refreshes HTML after edits |

Parallel extraction: `--workers` or `DV_AGENT_MAX_WORKERS` (cap 4, default 1) fetches chunks
concurrently while the main thread applies results in original order, so the graph is identical to a
sequential build. The tracer is locked and spans carry explicit parents.

## Run directory

`runs/<repo>/` (ignored by Git): `manifest.json`, `text/`, `chunks.jsonl`, `graph.json`,
`build_stats.json`, `dense/`, `llm_cache/`, `interfaces.*`, `registers.*`, `strategy.*`,
`test_plan.json`, `testplan_doc.*` (JSON, Markdown, HTML), `trace.jsonl`. Each stage is reused while its inputs, model and graph
are unchanged; `--force` reruns a stage; `--fresh` also clears the response cache
(`pipeline --fresh` clears every generated artifact, and refuses a folder that is not a run directory).

## Commands

| Command | Stage |
|---|---|
| `dv-agent ingest <repo>` | 1 |
| `dv-agent build-graph --out runs/<repo> [--llm auto\|on\|off]` | 2 |
| `dv-agent query "<text>"`, `context "<topic>" \| --requirement REQ-...`, `features`, `lineage <id>` | 3, lineage |
| `dv-agent interfaces`, `registers`, `strategy` (`--scope`, `--force`, `--fresh`) | 4a-4c |
| `dv-agent testplan [--scope] [--template]` | 5 |
| `dv-agent plan REQ-...` | per-requirement items (older, overlaps `testplan`) |
| `dv-agent pipeline <repo> [--testplan] [--fresh]` | 1-5 in order |
| `dv-agent usage [--last N] [--trace ID]` | tokens per run and per model call |

## Status

Offline: all stages implemented and tested (`pytest -q`, fake model), and live Meta API runs are recorded
(see Model integration). Not yet: refuse-and-repair in stage 2, the sign-off command, and hidden coverage data.
Retrieval quality is measured with `dv-agent evaluate --out runs/<run> --ablate --table`; on the 24 labelled
UART questions graph propagation did not beat plain BM25, so no retrieval-improvement claim is made.
