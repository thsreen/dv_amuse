# dv_agent execution workflow

Which file runs first, second, and so on — for every `dv-agent` command,
with what each file does. Entry point is always `cli.py:main()`
(the `dv-agent` console script).

```
ingest → build-graph → {query|context|deps|features} → interfaces → registers → strategy → testplan
pipeline  = ingest + build-graph + [plan] + [testplan] in one command
usage / lineage = read-only views over trace.jsonl / graph.json
```

Coding flow (separate; never called from the spec pipeline):

```
rtl-interfaces [--build] → build-interface → build-uvm [--testplan]
```

All paths below are under `src/dv_agent/` unless noted.

## 1. `cli.py` — entry point (runs first, every command)

Loads `.env` (never overriding real env vars), parses subcommands, checks
prerequisites (`{out} is missing graph.json; run the earlier stage first`),
builds the LLM client / embedder from `MODEL_API_KEY` / `META_EMBED_MODEL`
(`--llm auto|on|off` controls whether a missing key is an error), points the
client at `runs/<repo>/llm_cache/`, calls exactly one `pipeline.run_*()`
function, and prints the resulting JSON. `lineage` and `build-uvm` are the
only commands that bypass `pipeline.py` (they call `graph.lineage()` and
`uvm.build_uvm()` directly). Exit code 2 with `error: ...` on usage errors.

## 2. `pipeline.py` — stage orchestrator (runs second)

Each `run_ingest()`, `run_build_graph()`, `run_query()`, `run_context()`,
`run_deps()`, `run_features()`, `run_interfaces()`, `run_registers()`,
`run_strategy()`, `run_test_plan()`, `run_testplan_doc()`, `run_usage()`
does three things: check whether saved output is still current (reuse
shortcut — returns `{"reused": true}` without calling the model), open a
trace span, and call the worker modules below in fixed order. Also owns
`clear_run()` / `clear_llm_cache()` for `--fresh` and the fixed run-directory
artifact list. The `pipeline` command just calls `run_ingest()` →
`run_build_graph()` → optional `run_test_plan()` → optional
`run_testplan_doc()` in one process, then totals token usage across the
stages that actually ran.

## 3. `ingest.py` — Stage 1: spec discovery + chunking (no LLM)

`discover()` walks the repo for spec files (PDF, DOCX, HTML, Markdown,
plain text; prefers `doc/` / `docs/` / `spec/`, skips design-source, bench
and tool-output directories; `--include GLOB` overrides; every skip gets a
recorded reason). Then `ingest()` extracts text (DOCX via stdlib
`zipfile`+ElementTree, HTML via `html.parser`, PDF via pypdf; legacy binary
`.doc` is reported SKIPPED) and slices it into chunks where every chunk is
an exact `[char_start:char_end]` slice with section path, page numbers and
SHA-256. Writes `manifest.json` (documents, status/reason, sha256, repo git
revision), `text/<doc>.txt`, `chunks.jsonl`. Re-ingesting invalidates all
derived artifacts (graph, steps, plans).

## 4. `graph.py` — Stage 2a: graph skeleton (no LLM)

`build_structure()` creates the always-on skeleton: L1 `chunk` nodes,
L3 `document` / `section` nodes, `PART_OF` / `NEXT` edges. Also owns
`save/load_graph` (NetworkX node-link JSON), `attach_artifact()` (records
each generated section, interface set and register map as graph nodes with
`DERIVED_FROM` edges so lineage keeps working after generation), and
`lineage()` (walks any node back through dependencies to every requirement
and source chunk behind it).

## 5. `extract.py` — Stage 2b: semantic extraction (LLM, per chunk)

`extract_requirements()` makes one `spec_requirements` LLM call per chunk,
producing L2 `requirement` nodes (verbatim `quote` verified as an exact
substring of the chunk — whitespace/typography tolerant — with
`status=DOCUMENTED`, `interpretation=INFERRED`,
`review_status=NOT_REVIEWED`) and `entity` nodes (merged by name/alias,
parent-qualified so ambiguous references don't link). `extract_dependencies()`
makes one `requirement_dependencies` call per entity group, inferring
`DEPENDS_ON` / `CONSTRAINS` / `REFINES` / `CONFLICTS_WITH` edges, each
requiring a verbatim evidence quote from an endpoint requirement and stored
as `status=INFERRED`. Skipped entirely in `--llm off` (structural graph
only). Known gap: extraction still drops rejected quotes instead of using
the repair loop (review P2).

## 6. `community.py` — Stage 2c: community summaries (no LLM)

Deterministic community detection (fixed seed) over L2 entities and
requirements, producing L3 summary nodes. Navigation aids only — surfaced
to the model as global context but never cited as evidence.

## 7. `dense.py` — Stage 2d: embedding index (LLM-adjacent)

Builds/loads the NumPy embedding index under `dense/` and scores chunks by
vector similarity at query time. Only active when `META_EMBED_MODEL` + key
are set; otherwise the pipeline reports dense as NOT_RUN and retrieval runs
BM25-only. No vector database — sized to the run directory by design.

## 8. `retrieval.py` — Stage 3a: fused seed retrieval + PageRank (no LLM)

`retrieve()`: BM25 and dense scores over L1–L3, each max-normalized and
combined convexly (score magnitudes kept — reciprocal rank fusion was
rejected for discarding lexical margins), then Personalized PageRank from
the seeds over typed, weighted edges, bounded by iteration count and
tolerance. Returns ranked L1 chunks only, each with per-component scores,
the graph path that reached it, and a human-readable explanation. Every
pipeline fetch starts here.

## 9. `graph_fetch.py` — Stage 3b: structured graph sources (no LLM)

`add_owner_edges()` (`HAS_PART`: register→field, interface→signal),
entity-centred context (an owned name resolves only with its owner named),
`dependency_closure()` / `dependency_order()` (transitive preconditions over
dependency edges, cycles reported as designer questions), global community
fetch, and coverage of requirements earlier sections haven't cited.
`dv-agent deps` exposes closure/order/cycles/conflicts directly.

## 10. `combined_fetch.py` — Stage 3c: path source + merge (no LLM)

Adds the `path` source: deterministic shortest weighted path from the
topic's anchors and seeds to each verified interface signal, register and
uncovered requirement (the deliberately small GRW-AS-inspired piece —
no random walks, D-017). `combined_fetch()` merges all six sources
(retrieval, entity, dependency, global, path, coverage) via adaptive
selection: each source keeps up to `min_per_source` of its best items, then
fills by score to the cap — an item reached by several sources lists them
all. Known gap: the path length filter can drop a valid bounded path
(review P2).

## 11. `testplan_context.py` — Stage 3d: evidence bundles (no LLM)

`fetch_context()` is the single funnel every generation step calls: it runs
`combined_fetch()` and assembles the versioned (`schema_version`) bundle —
`requirements` (statement, verbatim quote, kind, review status, full
citation), `dependency_requirements` (preconditions outside the retrieved
set), `dependencies`, `entities`, `evidence` (chunks with scores +
explanations), `navigation` (summaries, navigation only), `open_items`
(conflicts, unreviewed items), `retrieval` (provenance). `requirement_context()`
adds focus requirement + lineage; `feature_index()` drives the plan outline
(`dv-agent features`). `dv-agent context` prints the bundle directly.

## 12. `interfaces.py` — Stage 4a: signal isolation + grouping (LLM + repair)

Step 0 of every test plan. `extract_interfaces()`: fetch context →
one `testplan_interfaces` LLM call proposing signals (name, width, DUT-
relative direction, availability, defining quote, active level) →
`repair.structured_with_repair()` with deterministic checks (names and
quotes must be in the cited chunk; unstated direction/width/active level
marked "(not stated)") → grouping by interface functionality + connected
module type (bus signals stay together, sidebands get their own group;
exactly one group per signal; grouping always INFERRED; leftovers →
"Ungrouped signals" ASSUMED + designer question). Groups feed every later
section and are recorded as an `interface_definitions` graph node.
Writes `interfaces.json` / `.md`.

## 13. `registers.py` — Stage 4b: verified register map (LLM + repair)

`extract_registers()`: retain explicit Name/Address/Width/Access table rows first;
one `testplan_registers` call per source window by default (overlapping windows cover long chunks) →
checks require names, quotes, addresses, widths, access codes, reset values
and encodings to appear verbatim in chunk text → records merged across
chunks while conflicts (same register, different values) and overlaps
(fields sharing bits) are reported as designer questions, never silently
resolved → model identifies configurable registers and fields using verbatim supporting quotes;
read-only status and writable data payloads are distinguished from configuration controls.
Unclassified writable fields are review candidates, not confirmed configuration controls. Writes
`registers.json` / `.md`. The test plan's Register Map section renders from
this step with no model call.

## 14. `strategy.py` — Stage 4c: verification strategy (LLM + repair)

`build_strategy()`: reads saved `interfaces.json` / `registers.json`
(regenerating them first if missing or stale, recording their trace IDs) →
one `testplan_strategy` LLM call proposing agents (per interface group:
mode, drives, monitors, registers, sequences, correctness mechanisms),
agent + top-level scoreboards, register model, virtual sequences → checks
(each interface group covered by exactly one agent, agents drive only DUT
inputs of their own groups, passive agents never drive, registers /
scoreboard inputs / sequence agents must exist). Strategy is NOT_RUN when
the interface step has no verified groups. Writes `strategy.json` / `.md`.

## 15. `testplan_doc.py` — Stage 5: template-driven document (LLM + repair + claims)

`build_testplan_doc()`: loads the template
(`templates/testplan_quick_v0.json` — step blocks plus 11 sections, each
with `generator`, retrieval `queries` with `{scope}`, `instructions`) →
re-runs steps 4a–4c **in memory** so all sections share one consistent
interface/register/strategy view → renders each section in order, passing
earlier sections forward so names stay consistent. Generators: `title`
(deterministic, no LLM), `register_map` (rendered from step 4b),
`strategy` (step 4c), `entries` / `configurations` (one LLM call each:
fetch context → author call → `repair` → `claims.judge()`; citations
outside the supplied evidence dropped; uncited DOCUMENTED/INFERRED become
ASSUMED; Configurations requires every writable field with spec-stated
legal values). Each section becomes a `TPS-*` graph node
(`dv-agent lineage TPS-...`), a traced span, and part of the final
requirement-coverage report. Writes `testplan_doc.json` / `.md` / `.html`, including
the per-call token-usage section. HTML comes directly from the editable Markdown, with no
separate authoring or model call. `dv-agent render-testplan --out <run>` refreshes HTML
after Markdown edits without accessing the model. Failed register extraction blocks the
Configurations section's completeness and preserves the partial register inventory.
With `render-testplan --out <run> --serve`, a loopback-only viewer exposes the
HTML page's **Render testplan** button. Its POST action uses that same Markdown
renderer, saves the HTML, and refreshes the displayed report with no model calls.
The **Testplan** selector lists all generated plans below the chosen runs root;
`render-testplan --serve` defaults to the repository's `runs/`. The selected ID
travels in the page URL and is checked against discovered plans before reading
or rendering any file. Reloading the page discovers newly generated plans.

## 16. `planning.py` — older per-requirement items (LLM + rerank)

`build_test_plan()` (the `plan REQ-...` command): reranked retrieval +
sufficiency-judged bounded multi-hop expansion along dependency edges +
dependency preconditions → `test_plan.json` items, each with requirement
and chunk lineage, always `NEEDS_REVIEW`. Overlaps `testplan`; kept for
requirement-scoped items.

## 17. `llm.py` — the only file that calls the Meta API

`MetaClient.structured(name, instructions, payload, schema)`: Responses API
with `text.format: json_schema` (`META_API_STYLE=chat` switches to Chat
Completions), model `muse-spark-1.3` at `https://api.meta.ai/v1`,
bounded retries for rate limits / timeouts / server errors, errors
classified without echoing request details. Responses cached in
`llm_cache/` keyed by hash of model + call name + instructions + payload +
schema, so reruns cost nothing unless a prompt changed. Per-call token
capture (input / cached input / output / reasoning), estimated at ~4
chars/token and flagged when the API reports none. `FakeLLM` implements
the same `LLM` protocol and drives all offline tests. Live contract still
unverified (strict `json_schema` is the known risk; workshop uses
`json_object`).

## 18. `repair.py` — refuse-and-repair loop (no LLM itself)

`structured_with_repair(llm, tracer, name, instructions, payload, schema,
check)`: model answers → `check()` returns only model-fixable problems
(spec conflicts are excluded) → empty list accepts; otherwise the answer is
refused with `previous_output` + `refusal` reasons and repair instructions
→ up to `DV_AGENT_MAX_REPAIRS` repairs (default 2). After the budget, the
step's deterministic cleanup still applies and leftovers become one
designer question per step. Every refusal is a `refusal:<step>` trace span
and rendered in the Markdown ("Refused (attempt N)", "Repaired after N
refusal(s)"). Used by interfaces, registers, strategy, configurations and
entry sections — not yet by stage-2 extraction.

## 19. `claims.py` — independent claims check (one LLM call per section)

`judge()`: runs only after a section's deterministic checks pass. A
separate `claims_check` call evaluates each DOCUMENTED/INFERRED entry (and
each configuration's legal values/constraints) against *only* the text it
cites — because a valid citation doesn't make a claim true. Unsupported
claims are refused back to the author call through `repair.py`; claims
still unsupported after the budget are downgraded to ASSUMED with a note.
Off for Assumptions and Questions sections; a failed judge call reports
BLOCKED and never blocks the section.

## 20. `trace.py` — tracing (runs alongside everything)

`Tracer`: one trace per run appended to `runs/<repo>/trace.jsonl`, mirrored
to Langfuse when keys are set (a Langfuse failure disables the mirror
without stopping the run). Carries trace/span IDs, inputs, outputs, token
usage, refusal spans and lineage fact lists. `usage` and Langfuse lineage
views read this file.

## 21. `usage.py` — token accounting (reads the trace)

`run_totals()` / `summarize()` / `render()`: per model call and per run —
calls (API vs local cache), repairs, input, cached input (provider prompt
cache, part of input), uncached input, output, reasoning (part of output),
total; estimated calls flagged. Local cache hits consume nothing (shown as
`replayed`); `from_scratch` is what a fresh run would use. Every command's
output carries its run's totals; `dv-agent usage [--last N | --trace ID]`
reports across runs.

## 22. `evaluate.py` — retrieval metrics (standalone, no CLI)

`load_cases()` + recall@k / MRR computation over a labeled case file
(`eval/uart_cases.json`). Import from Python; wired into no command yet.
Every retrieval claim needs a measurement here before being stated as an
improvement.

## 23. `models.py` + `fsutil.py` — shared leaves (no pipeline logic)

`models.py`: shared Pydantic schemas. `fsutil.py`: `atomic_write_text`
(write-temp-then-rename so crashes never leave half-written artifacts).
Imported by nearly every file above; they call nothing in the pipeline.

## 24. `rtl/source.py` — coding flow 1: Verilog preprocessing (offline)

Resolves includes (`-I`), defines (`-D`), parameter overrides (`-P`) and
conditional compilation for the explicitly selected RTL files. No top
auto-detection — `--top` names the exact module.

## 25. `rtl/extractor.py` — coding flow 2: declaration extraction (offline)

Parses the preprocessed sources into ports/parameters with resolved widths
(ANSI/non-ANSI ports, fixed arrays, integer params, object macros).
Unsupported selected types/expressions fail explicitly — widths and
protocols are never guessed. (`rtl/constants.py` holds its resource
limits.) Writes `rtl_interfaces.json`.

## 26. `rtl/builder.py` — coding flow 3: JSON interface builder (offline)

Maps extraction onto `templates/rtl_interface_v0.json` → compact
`interface_definition.json` (`sources`, `direction_reference`,
`parameters`, `ports`; direction/width-or-range/name rows, optional
description last). Optional explicit `--groups` mapping; optional
SystemVerilog export only from original RTL (`build-interface` from saved
compact JSON is JSON-only — the compact form intentionally omits what
faithful SV export needs). `rtl/commands.py` is the thin CLI adapter
wiring `source` → `extractor` → `builder` for both `rtl-interfaces` and
`build-interface`.

## 27. `uvm.py` — coding flow 4: UVM scaffold (offline by default)

`build_uvm()` deterministically generates interface, transaction, config,
sequencer, driver, monitor, scoreboard (starts disabled — no expected-
behavior model; `check_sample` is the extension hook), agent, env, base
test plus plan-named sequences from the interface JSON and optional
`testplan_doc.json`. Clock is explicit and required; reset needs
`--reset` + `--reset-active` together (polarity never inferred).
`write_uvm()` writes the output and copies
`templates/common_uvc/{clock,reset}/` on every build with a
project-specific wiring guide. Optional `--llm on` translates bounded plan
strategy/configuration/stimulus into constant DUT-input controls only —
checked against widths, direction and plan citations, manifest stays
NEEDS_REVIEW. Compilation/simulation are separate NOT_RUN steps.

## Reuse shortcut (why a rerun may execute almost nothing)

Before doing work, each stage checks its saved output: `ingest` reuses on
matching document hashes + `--include` selection; `build-graph` on matching
mode/dense setting with no prior LLM failure; `interfaces` / `registers` /
`strategy` / `testplan` on matching inputs + template + model + graph build
(plus no BLOCKED sections for the test plan). `--force` reruns the stage
(still reading `llm_cache/`); `--fresh` also clears the cache;
`pipeline --fresh` clears the whole run directory but refuses folders that
aren't run directories.

## orchestrate-agent (separate entry point over both flows)

Bare `orchestrate-agent` (short alias: `orchestrate`) opens an interactive
terminal (`src/orchestrator_agent/repl.py`): a free-text request names a local
repository, which is scanned read-only and followed by an English execution
preview. Four commands are exposed: `/plan` generates the spec/RTL grounded
testplan, `/code` builds only cited documented items (running `/plan` first when
needed), `/run` executes the basic built smoke test, and `/regress` executes
every built test. `/plan` shows a live split-pane dashboard (`tui.py`):
steps checking off on the right, run counters plus observed token usage and
the current tool call on the left. Non-interactive `run|validate|status`
unchanged. Interactive flow `src/orchestrator_agent/flows/testplan_flow.json`;
advanced CLI flow `src/orchestrator_agent/flows/default_flow.json`;
full contract in `docs/ORCHESTRATOR.md`.
