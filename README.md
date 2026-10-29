# dv_agent

Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ([diagram](docs/architecture.png)).

Spec ingestion → dependency GraphRAG → traceable lineage, for any design repository
(UART16550 in `../baseline_repos/uart16550` is the prototype, not a constraint).

## Setup
```
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
cp .env.example .env   # add MODEL_API_KEY and optional Langfuse keys
```

## Use
```
.venv/bin/dv-agent ingest ../baseline_repos/uart16550          # -> runs/uart16550/
.venv/bin/dv-agent build-graph --out runs/uart16550            # L2 needs MODEL_API_KEY; --llm auto|on|off
.venv/bin/dv-agent query "THRE interrupt clear condition" --out runs/uart16550
.venv/bin/dv-agent lineage REQ-xxxxxxxxxx --out runs/uart16550
```
`ingest` discovers spec files (PDF, DOCX, HTML, Markdown, text) (prefers `doc/`, `docs/`, `spec/`; skips design-source, bench and tool-output directories;
`--include GLOB` overrides) and records every skip with a reason in `manifest.json`.

## Run directory
| File | Content |
|---|---|
| `manifest.json` | documents found, status/reason, sha256, repo git revision |
| `text/<doc>.txt` | cleaned text; every chunk is an exact `[char_start:char_end]` slice |
| `chunks.jsonl` | L1 chunks: section path, pages, offsets, sha256 |
| `graph.json` | NetworkX node-link graph (layers 1–3, typed weighted edges) |
| `trace.jsonl` | every span of every run; mirrored to Langfuse when keys are set |
| `llm_cache/` | responses keyed by prompt hash (reproducible, no repeat spend) |

## Graph
- **L1** `chunk`: immutable source text.
- **L2** `requirement` (verbatim `quote` verified against the chunk; `status=DOCUMENTED`,
  `interpretation=INFERRED`, `review_status=NOT_REVIEWED`) and `entity` (merged by name/alias).
- **L3** `document`/`section`: navigation only, never evidence.
- Edges: `PART_OF`, `NEXT`, `DERIVED_FROM`, `MENTIONS`, `APPEARS_IN`, and LLM-inferred
  `DEPENDS_ON`/`CONSTRAINS`/`REFINES`/`CONFLICTS_WITH` (each needs a verbatim evidence quote;
  `status=INFERRED`).

## Lineage for generated artifacts
```python
from dv_agent.graph import attach_artifact
lin = attach_artifact(G, tracer, "SVA-0001", "assertion", parents=["REQ-..."], content=sva_text)
```
Adds the artifact with `DERIVED_FROM` edges, walks back through dependencies to every fact and
source chunk, and logs that list on a `lineage:SVA-0001` span (Langfuse + `trace.jsonl`).

## Tests
`.venv/bin/python -m pytest -q` (offline, fake LLM). Live checks: `pytest -m live` with keys set.

## Retrieval and test plans
- `query` fuses BM25 and dense scores (dense only when `META_EMBED_MODEL` and `MODEL_API_KEY` are set), then propagates with Personalized PageRank; each evidence item lists components, a graph path and an explanation.
- `plan REQ-...` runs bounded multi-hop retrieval (rerank + sufficiency + dependency expansion), writes `test_plan.json`, and records each item in the graph with its requirement and chunk lineage. Items are always `NEEDS_REVIEW`.
- `dv_agent/src/dv_agent/evaluate.py` computes recall@k and MRR for a labeled case file (`load_cases`); no CLI yet.

## Reuse and `--force`
Each stage reuses its saved output when inputs are unchanged, so repeat runs do no work and spend no tokens:
- `ingest` is reused when the source-document hashes and `--include` selection match `manifest.json`. Re-ingesting invalidates the graph and test plan.
- `build-graph` is reused when `build_stats.json` matches the requested mode (LLM or structural) and dense setting, and the previous LLM stage did not fail.
- `plan` is reused when the requirement IDs and dense setting match `test_plan.json`.

`--force` on any command, or `dv-agent pipeline <repo> [--requirements REQ-...] --force`, reruns that stage. Forced reruns still read `runs/<repo>/llm_cache/`, so they cost tokens only for prompts that changed. To force fresh model calls, delete that cache directory.

## Fresh demo run
- `dv-agent pipeline <repo> --fresh` deletes every generated artifact in the run directory (manifest, chunks, text, graph, stats, test plan, dense index, LLM cache, trace) and reruns all stages. Nothing outside the fixed artifact list is touched, and it refuses a non-empty directory that has no run markers (manifest, build stats, graph or trace).
- `dv-agent build-graph --fresh` and `dv-agent plan ... --fresh` delete only `llm_cache/` and rerun, so the model is called again.

## Fetching test-plan knowledge (`testplan_context.py`)
No LLM calls; built only from specification-derived graph nodes. Bundle shape is versioned (`schema_version`) so a test-plan template can map onto it.
- `dv-agent context "<feature or topic>" --out runs/<repo> [--save bundle.json]`
- `dv-agent context --requirement REQ-... --out runs/<repo>` (adds `focus_requirement` and `lineage`)
- `dv-agent features --out runs/<repo>`: ordered sections and communities with their requirement IDs, to drive a test-plan outline.

Bundle fields: `requirements` (statement, verbatim quote, kind, review status, citation with document/page/section/chunk/offsets), `dependency_requirements` (preconditions outside the retrieved set), `dependencies` (inferred edges with rationale and evidence quote), `entities`, `evidence` (chunks with scores and explanations), `navigation` (section/community summaries, navigation only), `open_items` (conflicts, unreviewed dependencies and requirements), `retrieval`.
The `plan` command now also passes dependency preconditions to the model and allows citing them.

## Test-plan document (`testplan_doc.py`)
`dv-agent testplan --out runs/<repo> [--scope "<feature>"] [--template my_template.json] [--force|--fresh]`
or in one go: `dv-agent pipeline <repo> --fresh --testplan [--scope ...]`.

Writes `testplan_doc.json` (structured, with citations and lineage) and `testplan_doc.md` (readable).
The template is data: `src/dv_agent/templates/testplan_quick_v0.json` (the user's 10-section quick reference).
Each section has `generator` (`title` | `entries` | `register_map`), `queries` (`{scope}` placeholder),
`instructions`, optional `entry_kinds`, `include_kinds`, `collect_assumed`, `include_conflicts`.
- Every entry is tagged `[DOCUMENTED]`, `[INFERRED]` or `[ASSUMED]` with source IDs. Citations outside the
  supplied evidence are dropped; DOCUMENTED/INFERRED without citations become ASSUMED.
- Register map: DOCUMENTED addresses and reset values must appear verbatim in cited text, otherwise INFERRED.
- Later sections receive earlier ones (agents/sequences stay consistent). Assumptions collect ASSUMED
  entries from all sections; designer questions include specification conflicts and evidence gaps.
- Each section is a `test_plan_section` graph node (`dv-agent lineage TPS-...`) and a traced span with fact IDs.
- Reused unless template, scope, model or graph build changed, or a section was BLOCKED.

### Step 0: interface isolation (`interfaces.py`)
Runs before any test-plan section (template `interfaces` block; `"enabled": false` turns it off).
- Extracts every specification-defined signal: name, width, direction relative to the DUT, availability
  (build option or mode), defining quote. Names not found in the cited chunk are dropped; directions and
  widths not stated in the quote are marked "(not stated)".
- Groups signals by the interface's functionality and the type of module it connects to (`peer_type`).
  Bus signals stay together; sidebands (single wire or bundle) get their own group per functionality and
  module type. Each signal is in exactly one group; leftovers go to "Ungrouped signals" (ASSUMED) and raise
  a designer question. Grouping is always INFERRED.
- Groups are passed to every section and rendered after the title; recorded as an `interface_definitions`
  graph node with lineage.

## LLM mode and model settings
`--llm` on `build-graph` and `pipeline` (or `DV_AGENT_LLM_MODE`): `auto` (default) uses the LLM when
`MODEL_API_KEY` is set, `on` fails if it is not, `off` never calls the API (structural graph only).
`META_API_STYLE` must be `responses` or `chat`; `META_MAX_OUTPUT_TOKENS` (default 8192) must be a positive integer.

## Specification steps (each also runs inside `testplan`)
| Command | Output | What it does |
|---|---|---|
| `dv-agent interfaces --out runs/<repo>` | `interfaces.json`, `.md` | Signals grouped by functionality and connected module type; names, directions, widths and active levels checked against the spec text |
| `dv-agent registers --out runs/<repo>` | `registers.json`, `.md` | Register map: batched extraction per chunk, verified against chunk text, merged across chunks; conflicting values and overlapping fields are reported, not resolved; writable fields derived from access codes |
| `dv-agent strategy --out runs/<repo>` | `strategy.json`, `.md` | Agents per interface group (mode, drives, monitors, registers, sequences, correctness mechanisms), agent and top-level scoreboards, register model, virtual sequences; built from the saved interface and register steps (regenerated only if missing or stale) and checked against them |

All accept `--scope`, `--force` and `--fresh`. Strategy checks: every interface group covered by exactly one agent (uncovered groups become gaps and designer questions); agents drive only DUT inputs of their own groups; passive agents never drive; registers must exist in the register map; scoreboard and virtual-sequence agents must exist.

Test-plan sections (template `quick_reference_v0`): 1 Title, 2 Feature Description, 3 Register Map (from the register step, no model call), 4 High Level Verification Strategy (strategy step), 5 Configurations (every writable field with spec-stated legal values, distribution, constraints and reserved-bit handling; missing fields are added as ASSUMED and raised as questions), 6 Stimulus, 7 Checks, 8 Coverage, 9 Callouts, 10 Assumptions, 11 Questions to Designers.

## Formats
`.docx` (headings from Word heading styles or outline levels, tables as `cell | cell` rows, page numbers from page breaks) and `.html` (`h1`-`h6` headings, tables as rows; scripts and styles skipped) are parsed with the standard library. Legacy binary `.doc` is still reported SKIPPED.

## Refuse and repair (`repair.py`)
The step order is fixed. Inside the interface, register, strategy, configurations and test-plan section
steps, the checks review the model's answer; if they find problems the model can fix (a quote not in the
source, a value the specification does not state, an unknown citation, a signal an agent cannot drive,
an uncovered interface group, a missing writable field), the answer is refused and the model gets its
previous output plus the reasons. Up to `DV_AGENT_MAX_REPAIRS` repairs (default 2). Specification
conflicts are never refused; they stay designer questions. Problems left after the last repair are
cleaned up as before and raised as one designer question per step. Every refusal is a `refusal:<step>`
trace span and is shown in the Markdown ("Refused (attempt N)", "Repaired after N refusal(s)").

## Combined graph fetch (`graph_fetch.py`, `combined_fetch.py`)
Every fetch combines seed retrieval + PageRank, entity-centred traversal (register→field and interface→signal
owner edges), dependency closure and order, global community expansion, coverage of requirements not yet cited,
and shortest paths from the topic to the verified signals and registers (a deliberately small take on the
GRW-AS idea; no AssertionForge code). Adaptive selection keeps every source represented. See `docs/ARCHITECTURE.md`. Commands: `dv-agent context "<topic>" [--global N]`,
`dv-agent deps REQ-...`.

## Token usage (`usage.py`)
Every model call records the usage the Meta Model API reports: input, cached input (served from the provider's
prompt cache, part of input), output and reasoning (part of output). Calls whose response reports no usage are
estimated at about 4 characters per token and counted as estimated.
- Final result: `testplan_doc.json` (`token_usage`) and a "Token usage" section in `testplan_doc.md`, per model
  call, for the test-plan run and the graph build it used: calls (API / local cache), repairs, input, cached
  input, uncached input, output, reasoning, total.
- Every command's output includes `usage` for its run; `dv-agent pipeline` totals the stages that actually ran.
- Calls answered from the local response cache (`llm_cache/`) consume nothing; their original usage is shown as
  `replayed`, and `from_scratch` is what a fresh run would use.
- `dv-agent usage --out runs/<repo> [--last N | --trace ID]`: totals per run and per model call.
