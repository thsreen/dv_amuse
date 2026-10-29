# dv_agent execution workflow

Which file runs first, second, and so on — for every `dv-agent` command.
Entry point is always `src/dv_agent/cli.py:main()` (`dv-agent` console script),
which loads `.env`, parses args, and dispatches to one function in
`src/dv_agent/pipeline.py`. Each pipeline stage opens its own trace span
(`trace.py`) appended to `runs/<repo>/trace.jsonl`.

## Default specification-driven test-plan flow

```
ingest → build-graph → {query|context|deps|features} → interfaces → registers → strategy → testplan
pipeline  = ingest + build-graph + [plan] + [testplan] in one command
usage / lineage = read-only views over trace.jsonl / graph.json
```

### 1. `dv-agent ingest <repo>` — spec discovery + chunking (no LLM)

1. `cli.py` → `pipeline.run_ingest()`
2. `ingest.py:discover()` — find spec files (PDF/DOCX/HTML/MD/text), skip
   design-source/bench/tool-output dirs, record every skip with a reason
3. `ingest.py:ingest()` — extract text, split into chunks
4. Writes: `manifest.json`, `text/<doc>.txt`, `chunks.jsonl`

### 2. `dv-agent build-graph --out runs/<repo>` — 3-layer graph

1. `cli.py` → `pipeline.run_build_graph()`
2. `graph.py:build_structure()` — L1 chunks + L3 document/section nodes,
   `PART_OF` / `NEXT` edges (always runs, no LLM)
3. `extract.py:extract_requirements()` — one `spec_requirements` LLM call per
   chunk → L2 requirement/entity nodes, `DERIVED_FROM` / `MENTIONS` edges
   (skipped in `--llm off`; quotes verified verbatim against chunk text)
4. `extract.py:extract_dependencies()` — one `requirement_dependencies` LLM call
   per entity group → `DEPENDS_ON` / `CONSTRAINS` / `REFINES` /
   `CONFLICTS_WITH` edges (INFERRED, evidence quote required)
5. `community.py:build_communities()` — deterministic L3 community summaries
   (navigation only, never evidence)
6. `dense.py:build_index()` — NumPy embedding index (only if
   `META_EMBED_MODEL` + key are set)
7. Writes: `graph.json`, `build_stats.json`, `dense/`

### 3. Read-only retrieval (no LLM calls)

| Command | Chain |
|---|---|
| `query "<text>"` | `pipeline.run_query()` → `retrieval.py:retrieve()` (BM25 + dense seeds, fused → Personalized PageRank → rerank data, paths, explanations) |
| `context "<topic>"` / `--requirement` | `pipeline.run_context()` → `testplan_context.py:fetch_context()` → `combined_fetch.py:combined_fetch()` (retrieval + entity + dependency + global + path + coverage sources, adaptive selection) |
| `deps REQ-...` | `pipeline.run_deps()` → `graph_fetch.py:dependency_closure()` + `dependency_order()` |
| `features` | `pipeline.run_features()` → `testplan_context.py:feature_index()` |
| `lineage <id>` | `cli.py` → `graph.py:lineage()` directly (no pipeline step) |
| `usage` | `pipeline.run_usage()` → `usage.py:run_totals()` over `trace.jsonl` |

Internal fetch order inside `fetch_context()`: `retrieval.py` seeds →
`graph_fetch.py` entity/dependency/global/coverage → `combined_fetch.py`
shortest-path source → adaptive merge. Every item records its sources + path.

### 4a. `dv-agent interfaces` — step 0, signal isolation + grouping

1. `cli.py` → `pipeline.run_interfaces()`
2. `interfaces.py:extract_interfaces()`:
   - `testplan_context.fetch_context()` gathers the evidence bundle
   - `llm.py:MetaClient.structured("testplan_interfaces")` proposes signals
   - `repair.py:structured_with_repair()` — deterministic checks refuse bad
     output (unknown names, quotes not in chunk, ungrouped signals) and the
     model repairs, up to `DV_AGENT_MAX_REPAIRS` (default 2)
   - cleanup: one group per signal, unstated direction/width/active level
     marked, leftovers → ASSUMED + designer question
3. Writes: `interfaces.json`, `interfaces.md`

### 4b. `dv-agent registers` — verified register map

1. `cli.py` → `pipeline.run_registers()`
2. `registers.py:extract_registers()` — same shape as 4a, batched
   `testplan_registers` call per chunk group: names, quotes, addresses,
   widths, access, reset values must appear verbatim in chunk text; records
   merged across chunks; conflicts/overlaps reported, never resolved
3. Writes: `registers.json`, `registers.md`

### 4c. `dv-agent strategy` — agents, scoreboards, sequences

1. `cli.py` → `pipeline.run_strategy()`
2. `strategy.py:build_strategy()` — reads saved `interfaces.json` /
   `registers.json` (regenerates them first if missing/stale), then one
   `testplan_strategy` LLM call with repair: every interface group covered by
   exactly one agent, agents drive only DUT inputs of their own groups
3. Writes: `strategy.json`, `strategy.md`

### 5. `dv-agent testplan` — template-driven document

1. `cli.py` → `pipeline.run_testplan_doc()`
2. `testplan_doc.py:build_testplan_doc()`:
   - loads template (`templates/testplan_quick_v0.json`): step blocks +
     12 sections, each with generator, queries, instructions
   - runs steps 4a–4c **in memory** (`extract_interfaces` →
     `extract_registers` → `build_strategy`) so sections share one consistent
     interface/register/strategy view
   - optional section 4 (`--rtl-graph`): `rtl_observations.build_observations()` → bounded model-requested RTL graph queries → citation/support checks and repair → RTL designer review. Observations feed required strategy handling and cited later plan proposals. No graph is read without explicit opt-in (D-032; see RTL_OBSERVATIONS.md).
   - per specification section: `testplan_context.fetch_context()` (or `section_context()`)
     → `testplan_entries` / `testplan_configurations` LLM call →
     `repair.structured_with_repair()` → `claims.py:judge()` (separate
     `claims_check` call verifies each DOCUMENTED/INFERRED claim against only
     its cited text; failures refused back, leftovers downgraded to ASSUMED)
   - `graph.py:attach_artifact()` records each section as a `TPS-*` node with
     `DERIVED_FROM` lineage; `usage.py` totals tokens per call
3. Writes: `testplan_doc.json`, `testplan_doc.md`

### 6. `dv-agent plan REQ-...` — older per-requirement items

`cli.py` → `pipeline.run_test_plan()` → `planning.py:build_test_plan()`
(rerank + sufficiency-checked multi-hop + dependency expansion).
Overlaps `testplan`; kept for requirement-scoped items. Writes `test_plan.json`.

### 7. `dv-agent pipeline <repo> [--testplan]` — all-in-one

`cli.py` runs in fixed order, same process:
`run_ingest()` → `run_build_graph()` → optional `run_test_plan()` →
optional `run_testplan_doc()`, then totals usage across the stages that ran.

## Coding flow (separate; never called from the spec pipeline)

RTL extraction and interface building live in `src/rtl_agent/`, with an independent
`python -m rtl_agent` CLI. Existing `dv-agent` subcommands forward to this package.
The UVM generator remains in `src/dv_agent/uvm.py` and imports interface helpers from `rtl_agent`.

```
rtl-interfaces [--build] → build-interface → build-uvm [--testplan]
```

| Command | Chain |
|---|---|
| `rtl-interfaces <files> --top ...` | `cli.py` → `rtl_agent/commands.py:run_rtl_command()` → `rtl_agent/source.py` (preprocess: includes, `-D`, `-P`, conditionals) → `rtl_agent/extractor.py:extract_interface()` (ports/params) → `rtl_agent/builder.py` (only with `--build`) → writes `rtl_interfaces.json` + `interface_definition.json` (+ optional `--emit-sv` SystemVerilog) |
| `build-interface rtl_interfaces.json` | `cli.py` → `rtl_agent/commands.py` → `rtl_agent/builder.py:build_interface()` → writes `interface_definition.json` (JSON only; no SV from compact JSON) |
| `build-uvm interface_definition.json` | `cli.py` → `uvm.py:build_uvm()` (deterministic interface/item/cfg/sequencer/driver/monitor/scoreboard/agent/env/test + optional `--testplan` named sequences; optional `--llm on` bounded plan-to-control extraction) → `uvm.py:write_uvm()`; copies `templates/common_uvc/{clock,reset}/` every build |

## Orchestrator (separate entry point over both flows)

`orchestrate-agent run --flow <flow.json> --out <dir>` (`src/orchestrator_agent/`)
executes DV and RTL tools step by step from a flow contract: recommended order,
budgets, and a strict never-do list (`docs/ORCHESTRATOR.md`). Default flow:
`flows/default_flow.json` (spec ingest/graph → RTL ports/graph → spec
interfaces/registers/strategy/testplan with opt-in RTL observations → gated
UVM build). A bounded model decider may revisit/skip/stop; every budget,
timeout, violation or gate reverts to the owner (exit 3 + review file).

## Cross-cutting files (used by many steps, never a stage)

- `llm.py` — `MetaClient.structured()`: Responses API + strict `json_schema`
  (or chat style), retries, `llm_cache/` keyed by prompt hash
- `repair.py` — `structured_with_repair()`: check → refuse with feedback →
  bounded model repair → leftovers become designer questions
- `claims.py` — `judge()`: independent claim-vs-citation check after
  deterministic checks pass
- `trace.py` — `Tracer`: every span to `trace.jsonl`, mirrored to Langfuse
  when keys are set
- `usage.py` — token accounting (input / cached / output / reasoning,
  API vs replayed cache hits)
- `models.py`, `fsutil.py` — shared schemas, atomic writes
- `evaluate.py` — recall@k / MRR harness over `eval/uart_cases.json` (no CLI)

## Reuse shortcut (why a rerun may execute almost nothing)

Before doing work, each stage checks its saved output: `ingest` reuses on
matching doc hashes; `build-graph` on matching mode/dense setting;
`interfaces`/`registers`/`strategy`/`testplan` on matching inputs + template +
model + graph build. `--force` reruns the stage (still reading `llm_cache/`);
`--fresh` also clears the cache; `pipeline --fresh` clears the whole run dir.
