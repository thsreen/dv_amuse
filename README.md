# dv_agent

Silicon Copilot is a design-verification agent. From a one-line request, a specification and RTL it produces a
cited test plan and a UVM testbench, then compiles and simulates the testbench. Muse Spark does the semantic work;
checks outside the model refuse what they cannot verify; an engineer has the final say.

## Quickstart

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
cp .env.example .env   # add MODEL_API_KEY
tmux new -s dv         # so a dropped connection cannot stop a run
.venv/bin/python -m orchestrator_agent --mode basic --quick-testing-auto-approve-inferences
```

Then describe the design, for example `Verification collateral for the 8 bit UART in ../baseline_repos/uart16550`, and run:

| Command | What it does |
|---|---|
| `/plan` | Writes the cited test plan for the build the request selected |
| `/code` | Generates the testbench one unit at a time, resuming from saved answers, and ends with a summary of what was built, deferred, set aside and left open |
| `/run` | Compiles and simulates the first test, and saves a coverage report |
| `/run wave` | Also saves an FST waveform and sends it to the configured Telegram chat |
| `/regress` | Runs every built test |

`/run`, `/run wave` and `/regress` need `xezim` and a UVM source release (`XEZIM_BIN`, `XEZIM_UVM_DIR`). If the model API is slow and
plan sections time out, set `META_REQUEST_TIMEOUT_SECONDS=300`.

**Current status:** the 8-bit UART16550 runs end to end live: 13 of 13 plan sections, and a script-chosen test, `quick_basic`, passes on the real
RTL with 2 scoreboard comparisons, 37 of 37 assertions and 0 UVM errors. This is a prototype result under quick testing, with test-only approvals,
the model's own tests set aside and 4 features deferred. It is not verification of the design. See [docs/CODE_REVIEW_STATUS.md](docs/CODE_REVIEW_STATUS.md)
and [docs/QUICK_TESTING.md](docs/QUICK_TESTING.md).

Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ([diagram](docs/architecture/end_to_end.svg)).

Current review/status: [docs/CODE_REVIEW_STATUS.md](docs/CODE_REVIEW_STATUS.md).
Separate RTL coding flow: [JSON interface extractor and builder](docs/RTL_INTERFACES.md), using the
[basic JSON template](src/rtl_agent/templates/rtl_interface_v0.json).
The RTL extractor and interface builder live in `src/rtl_agent/`. Run them independently with
`.venv/bin/python -m rtl_agent`; existing `dv-agent` subcommands still work.

RTL hierarchy/dataflow/domain graph construction and combined Graph-RAG fetching:
[docs/RTL_GRAPH_RAG.md](docs/RTL_GRAPH_RAG.md).
Interactive orchestrator: `.venv/bin/orchestrate-agent`; describe a local
repository, then use `/plan`, `/code`, `/run` or `/regress`. See
[docs/ORCHESTRATOR.md](docs/ORCHESTRATOR.md).
Separate UVM coding flow: [scaffold generator](docs/UVM_SCAFFOLD.md).
UVM agent components and fill points: [agent template catalog](src/dv_agent/templates/uvm_agent/template.json).

Spec ingestion → dependency GraphRAG → traceable lineage, for any design repository
(UART16550 in `../baseline_repos/uart16550` is the prototype, not a constraint).

## Setup
```
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
cp .env.example .env   # add MODEL_API_KEY and optional Langfuse keys
```
Langfuse mirrors span names, timings and token counts only. Prompts, specification text and model output stay in
the local `trace.jsonl` unless you set `LANGFUSE_CAPTURE_CONTENT=1`.

`tools/xezim` (simulator) and `tools/e2e_sim` (ephemeral cloud simulation nodes) are optional git submodules.
Planning, retrieval and code generation do not need them; clone without `--recurse-submodules` and initialise only
what you use, for example `git submodule update --init tools/xezim`.

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
from dv_agent.graph.graph import attach_artifact
lin = attach_artifact(G, tracer, "SVA-0001", "assertion", parents=["REQ-..."], content=sva_text)
```
Adds the artifact with `DERIVED_FROM` edges, walks back through dependencies to every fact and
source chunk, and logs that list on a `lineage:SVA-0001` span (Langfuse + `trace.jsonl`).

## Tests
`.venv/bin/python -m pytest -q` (offline, fake LLM). Live checks: `pytest -m live` with keys set.

## Retrieval and test plans
- `query` fuses BM25 and dense scores (dense only when `META_EMBED_MODEL` and `MODEL_API_KEY` are set), then propagates with Personalized PageRank; each evidence item lists components, a graph path and an explanation.
- `plan REQ-...` runs bounded multi-hop retrieval (rerank + sufficiency + dependency expansion), writes `test_plan.json`, and records each item in the graph with its requirement and chunk lineage. Items are always `NEEDS_REVIEW`.
- `dv-agent evaluate --out runs/<run> --ablate --table` computes recall@k and MRR on `eval/uart_cases.json` (`src/dv_agent/retrieval/evaluate.py`), with and without graph propagation. No model call.

## Reuse and `--force`
Each stage reuses its saved output when inputs are unchanged, so repeat runs do no work and spend no tokens:
- `ingest` is reused when the source-document hashes and `--include` selection match `manifest.json`. Re-ingesting invalidates the graph and test plan.
- `build-graph` is reused when `build_stats.json` matches the requested mode (LLM or structural) and dense setting, and the previous LLM stage did not fail.
- `plan` is reused when the requirement IDs and dense setting match `test_plan.json`.

`--force` on any command, or `dv-agent pipeline <repo> [--requirements REQ-...] --force`, reruns that stage. Forced reruns still read `runs/<repo>/llm_cache/`, so they cost tokens only for prompts that changed. To force fresh model calls, delete that cache directory.

## Fresh demo run
- `dv-agent pipeline <repo> --fresh` deletes every generated artifact in the run directory (manifest, chunks, text, graph, stats, test plan, dense index, LLM cache, trace) and reruns all stages. Nothing outside the fixed artifact list is touched, and it refuses a non-empty directory that has no run markers (manifest, build stats, graph or trace).
- `dv-agent build-graph --fresh` and `dv-agent plan ... --fresh` delete only `llm_cache/` and rerun, so the model is called again.

## Fetching test-plan knowledge (`plan/testplan_context.py`)
No LLM calls; built only from specification-derived graph nodes. Bundle shape is versioned (`schema_version`) so a test-plan template can map onto it.
- `dv-agent context "<feature or topic>" --out runs/<repo> [--save bundle.json]`
- `dv-agent context --requirement REQ-... --out runs/<repo>` (adds `focus_requirement` and `lineage`)
- `dv-agent features --out runs/<repo>`: ordered sections and communities with their requirement IDs, to drive a test-plan outline.

Bundle fields: `requirements` (statement, verbatim quote, kind, review status, citation with document/page/section/chunk/offsets), `dependency_requirements` (preconditions outside the retrieved set), `dependencies` (inferred edges with rationale and evidence quote), `entities`, `evidence` (chunks with scores and explanations), `navigation` (section/community summaries, navigation only), `open_items` (conflicts, unreviewed dependencies and requirements), `retrieval`.
The `plan` command now also passes dependency preconditions to the model and allows citing them.

## Test-plan document (`plan/testplan_doc.py`)
`dv-agent testplan --out runs/<repo> [--scope "<feature>"] [--template my_template.json] [--force|--fresh]`
or in one go: `dv-agent pipeline <repo> --fresh --testplan [--scope ...]`.

Writes `testplan_doc.json` (structured, with citations and lineage), `testplan_doc.md` (editable)
and `testplan_doc.html` (readable, standalone and printable). HTML is rendered directly from the
same Markdown, without another model call. After editing the Markdown, run
`dv-agent render-testplan --out runs/<repo>` to refresh HTML without regenerating the plan.
For a testplan selector and **Render testplan** button in the HTML page, start the local viewer once:
`dv-agent render-testplan --serve`. Open the printed URL and select any generated plan under `runs/`.
Save edits to that plan's `testplan_doc.md`, then click the button to refresh it and save its HTML copy.
The selector also finds plans generated while the viewer is running when the page is reloaded.
`--out runs/<repo> --serve` opens that plan first and lists its sibling runs; `--out runs --serve`
opens the full runs directory. No model calls are made. `--port` selects a port (default 8765);
Ctrl+C stops the viewer.
The template is data: `src/dv_agent/templates/testplan_quick_v0.json` (the user's 10-section quick reference).
Each section has `generator` (`title` | `entries` | `register_map`), `queries` (`{scope}` placeholder),
`instructions`, optional `entry_kinds`, `include_kinds`, `collect_assumed`, `include_conflicts`.
- Every entry is tagged `[DOCUMENTED]`, `[INFERRED]` or `[ASSUMED]` with source IDs. Citations outside the
  supplied evidence are dropped; DOCUMENTED/INFERRED without citations become ASSUMED.
- Methodology rules (`src/dv_agent/templates/methodology_rules_v0.json`, extended via
  `--methodology-rules my_rules.json`) are natural-language DV-agent recommendations that need no
  specification source. Entries citing only a rule are DOCUMENTED with reason 'Recommended by DV agent'
  and cite the rule ID (e.g. METH-XPROP-1); enforced rules are force-injected into their sections.
  Same rule ID in your file replaces the shipped rule.
- Register map: DOCUMENTED addresses and reset values must appear verbatim in cited text, otherwise INFERRED.
- Explicit Name/Address/Width/Access specification tables supply the register inventory even if a model
  call fails. Model enrichment uses one source window per call, retaining the entire selected text.
  The LLM identifies configurable registers and fields with supporting specification quotes;
  data/FIFO payloads and read-only status are distinguished from configuration controls. These
  reviewed classifications, access codes, legal encodings and access conditions feed Configurations.
  Failed extraction keeps partial maps visible and blocks configuration completeness.
- Token-limit model responses retry with a larger output budget (three attempts total, capped by
  `META_MAX_OUTPUT_TOKENS_CEILING`, default 32768). Other incomplete responses remain explicit failures.
- Later sections receive earlier ones (agents/sequences stay consistent). Assumptions collect ASSUMED
  entries from all sections; designer questions include specification conflicts and evidence gaps.
- Each section is a `test_plan_section` graph node (`dv-agent lineage TPS-...`) and a traced span with fact IDs.
- Reused unless template, scope, model or graph build changed, or a section was BLOCKED.

### Step 0: interface isolation (`plan/interfaces.py`)
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
| `dv-agent registers --out runs/<repo>` | `registers.json`, `.md` | Source-table inventory plus model extraction per source window, merged with citations; configurable registers/fields identified by the LLM and checked against access; conflicts and overlaps reported for review |
| `dv-agent strategy --out runs/<repo>` | `strategy.json`, `.md` | Agents per interface group (mode, drives, monitors, registers, sequences, correctness mechanisms), agent and top-level scoreboards, register model, virtual sequences; built from the saved interface and register steps (regenerated only if missing or stale) and checked against them |

All accept `--scope`, `--force` and `--fresh`. Strategy checks: every interface group covered by exactly one agent (uncovered groups become gaps and designer questions); agents drive only DUT inputs of their own groups; passive agents never drive; registers must exist in the register map; scoreboard and virtual-sequence agents must exist.

Test-plan sections (template `quick_reference_v0`): 1 Title, 2 Feature Description, 3 Register Map, 4 Observations from RTL (opt-in, design-engineer review), 5 High Level Verification Strategy, 6 Configurations, 7 Stimulus, 8 Checks, 9 Coverage, 10 Callouts, 11 Assumptions, 12 Questions to Designers.

Supply `--rtl-graph <rtl_graph.json> [--rtl-scope <instance>]` to `testplan` or `pipeline --testplan`
to add source-backed implementation concerns before strategy. The model can request bounded graph
fetches; observations and derived tests remain INFERRED and require RTL design engineer review.
See [docs/RTL_OBSERVATIONS.md](docs/RTL_OBSERVATIONS.md). Without the flag the section is NOT_RUN.

## Formats
`.docx` (headings from Word heading styles or outline levels, tables as `cell | cell` rows, page numbers from page breaks) and `.html` (`h1`-`h6` headings, tables as rows; scripts and styles skipped) are parsed with the standard library. Legacy binary `.doc` is still reported SKIPPED.

## Refuse and repair (`quality/repair.py`)
The step order is fixed. Inside the interface, register, strategy, configurations and test-plan section
steps, the checks review the model's answer; if they find problems the model can fix (a quote not in the
source, a value the specification does not state, an unknown citation, a signal an agent cannot drive,
an uncovered interface group, a missing writable field), the answer is refused and the model gets its
previous output plus the reasons. Up to `DV_AGENT_MAX_REPAIRS` repairs (default 2). Specification
conflicts are never refused; they stay designer questions. Problems left after the last repair are
cleaned up as before and raised as one designer question per step. Every refusal is a `refusal:<step>`
trace span and is shown in the Markdown ("Refused (attempt N)", "Repaired after N refusal(s)").

## Combined graph fetch (`retrieval/graph_fetch.py`, `retrieval/combined_fetch.py`)
Every fetch combines seed retrieval + PageRank, entity-centred traversal (register→field and interface→signal
owner edges), dependency closure and order, global community expansion, coverage of requirements not yet cited,
and shortest paths from the topic to the verified signals and registers (a deliberately small take on the
GRW-AS idea; no AssertionForge code). Adaptive selection keeps every source represented. See `docs/ARCHITECTURE.md`. Commands: `dv-agent context "<topic>" [--global N]`,
`dv-agent deps REQ-...`.

## Token usage (`core/usage.py`)
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

## Claims check (`quality/claims.py`)
A valid citation does not make a claim true. In free-text sections and Configurations, after the deterministic
checks pass, a separate `claims_check` model call judges each DOCUMENTED or INFERRED claim against only the text it
cites. Unsupported claims are refused back to the author call (refuse-and-repair); any still unsupported after the
repair budget are downgraded to ASSUMED and raised as a designer question. Off for Assumptions and Questions; a
failed judge call is reported as BLOCKED and never blocks the section (D-025).

Repository protection policy: [Protected files](docs/PROTECTED_FILES.md).
