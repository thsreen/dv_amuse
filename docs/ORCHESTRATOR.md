# Orchestrator agent

`orchestrate-agent` runs the DV agent and the RTL agent step by step from a
**flow JSON contract**: the recommended tool order, the execution budgets, and
a strict never-do list. Without a model it walks the recommended order; with
one, a bounded decider may revisit a completed step with a sharper follow-up
question, skip an optional step, or stop. Every budget exhaustion, timeout,
rule violation and review gate reverts to the owner with a review file and a
resume command.

## Quick-testing auto approval

For a demo or short development check, start:

```bash
.venv/bin/python -m orchestrator_agent --quick-testing-auto-approve-inferences
```

Enter `/code`. Infrastructure review requests are evaluated and automatically
approved in a separate test-only run. Reasoning and assumptions are recorded as
inferred; the original plan remains unchanged. This is **quick testing only**, not
human/RTL-engineer sign-off. Without the flag, normal human review applies.
See [review workflow and limits](HUMAN_REVIEW.md#quick-testing-auto-approver-explicit-opt-in).

## Interactive testplan flow

The current-task panel wraps task names, detailed messages and retry status instead
of truncating them. Below 80 terminal columns the dashboard stacks its panels,
with current progress last so it remains visible when the display scrolls.

Test-plan sections declare their prerequisites through `depends_on` in
`src/dv_agent/templates/testplan_quick_v0.json`. Interface extraction precedes
strategy; register extraction precedes configuration and implementation planning;
stimulus depends on the implementation plan and configuration, checks depend on
stimulus, and coverage depends on stimulus and checks. Dependencies must reference
earlier sections or the extraction steps `@interfaces` and `@registers`.

An unresolved prerequisite blocks its dependent section before any model call.
Execution is strictly sequential: every section also requires successful completion
of the immediately preceding section, including integration, assumptions and designer
questions. Failed interface extraction also prevents register extraction. This rule
applies to custom templates even when they omit `depends_on`. Only a genuinely
inapplicable step (such as RTL observations without an RTL graph) may be skipped.
Register extraction, Feature Description and Register Map are absolute prerequisites.
Disabling register extraction, omitting these sections or reordering downstream work
cannot bypass the gate. Missing or incomplete foundations keep the final plan blocked.
Blocker reports and checkpoints are still written without further model calls.
JSON records each
dependency's status, reason and satisfaction, plus `blocked_by` links. Downstream
calls receive actual register/field and configuration context. A successfully extracted empty register
map does not require a configuration section.

The JSON and both report views show generation readiness separately from engineer
review. Any required blocked or unfinished section makes final readiness `BLOCKED`
and generation `PARTIAL`; interrupted generation also remains blocked. The
orchestrator uses the same aggregate status. Standalone `testplan` and
`pipeline --testplan` return exit code 1 for blocked plans. Restart an existing
orchestrator process to load these changes; previous run artifacts are retained.

Basic lexical RAG is the default. Start:

```sh
.venv/bin/python -m orchestrator_agent
```

Then enter `Generate verification collateral for ../baseline_repos/uart16550` and `/plan`.
Afterward type `/code`. It binds clock and reset (no model call), then each interface, then individual feature tasks.
Every unit repeats retrieve → understand/pseudocode → implement → validate → checkpoint.
After all interface scaffolds, a per-interface assessment selects scaffold-only, utility configuration,
passive monitoring or a full agent; only the chosen components are built. Decisions and reasons are
saved under `infrastructure_needs/` and shown in the execution queue. Features are grouped by interface or function; a dedicated dependency pass chooses sequence
extension, typed `p_sequencer` controls or ordering. One feature completes before the next starts.
`CODE_EXECUTION_PLAN.md` and the work directory's `execution_plan.json` record this queue.
Xezim compilation/simulation is deferred to `/run` or `/regress`. The terminal shows the
English preview and progress dashboard, including the current unit and elapsed time.
Noninteractive terminals receive plain progress lines; there are no timer-only redraws.

In a restarted session, `/code` automatically selects the latest successful compatible documented
testplan and restores its saved RTL interface/source list. Naming a repository first restricts this
selection to that design. Incomplete plans, inferred RTL specifications, failed workflows and missing
source files are excluded. With no matching saved plan, `/code` runs `/plan` first for the selected
repository. `/fresh` disables automatic saved-plan restoration for that session.

Code remains under the selected run's `code/`; dependency/pseudocode documents are indexed by
`code_work_manifest.json`. `code_trace.jsonl` records progress and `code_result.json` records the
outcome/duration separately from the planning result. Interrupted builds retain successful checkpoints;
retry `/code` to resume matching work. Compilation failures are reported as blocked. Generated
expectations still require review. `/run` and `/regress` execute the generated tests separately.
Without an enabled model or explicit implementation contract, the existing limited smoke scaffold
remains available and is labeled accordingly.

The same four commands remain available. Advanced `run` also accepts `--mode graph`
for the model-built knowledge-graph analysis. `DV_AGENT_MODE=graph` is the
equivalent environment setting.

Basic mode targets a 10–15 minute UART-sized demo: it builds a local lexical chunk index without model
requirement/dependency extraction or embeddings, follows the fixed flow without model decider calls,
and retrieves source chunks directly for planning. Register extraction keeps every selected source
window and the deterministic register-table inventory, using two workers with deterministic merging.
Planning uses smaller retrieval/entry limits and no validation repair rounds or separate model claim
judges for ordinary sections. Citation, quote, register validation and inferred RTL review rules remain.
RTL observations retain their claim judge. The interactive/advanced orchestrator model client uses a
150-second request timeout and two API attempts in basic mode. Graph mode also defaults
to 150 seconds per request, retaining its five-attempt recovery. Set
`META_REQUEST_TIMEOUT_SECONDS` to override the request timeout.

The report explicitly identifies the reduced analysis scope. Requirement graph coverage is unavailable;
this is a review-required demo draft, not equivalent to the graph analysis. Successful responses still
checkpoint for same-directory recovery. API service latency and failures can exceed the target;
10–15 minutes is a target, not an enforced whole-run deadline. Live timing requires an unrestricted
terminal with API connectivity. Graph mode (`--mode graph`) builds the evidence graph first;
`basic` skips it.

Graph extraction saves and resumes completed batches automatically; generation API calls recover with at most five attempts. See [graph and API recovery](GRAPH_RECOVERY.md). Basic mode uses chunk-only lexical retrieval, while requirement/dependency extraction occurs in `spec_graph` before planning in graph mode.

Completed testplan sections immediately update partial JSON, Markdown and HTML
reports. Pending sections are labeled; interruptions preserve the latest output.
Detailed request/attempt diagnostics are in `<run>/dv/llm_requests.jsonl`, section
and exception spans in `<run>/dv/trace.jsonl`, and workflow progress/results in
`<run>/orchestrator_trace.jsonl`. Logs identify timeout duration, input size, retry
number and exception type without logging API credentials. See the recovery guide
for fields and the distinction between partial views and response-cache recovery.

Run `.venv/bin/orchestrate-agent` from this repository and describe the local
design repository in one sentence, for example:

```text
orch> Generate a UART16550 verification testplan from its specification and RTL.
```

The terminal scans the named repository without writing to it, identifies the
specification documents and RTL top, and immediately prints the steps it will
run in English. The testplan step expands into interface isolation, register
recovery, every section from the template, and Markdown/HTML rendering.
The default template has a separate **Verification Plan** immediately after **High Level Verification Strategy**.
Strategy defines the verification architecture; the plan describes implementation of sequences, monitors,
checks, scoreboards/predictors, coverage, and test integration using consistent component names.
Later Sequences and Stimulus, Checks and Scoreboards, Functional Coverage, and Integration and Reuse
sections elaborate that plan. Proposed implementation architecture remains INFERRED with source citations.
Generated JSON records ordered `subsections` for each content section: stable `id`, readable `heading`,
`layout` (bullets/table/expandable row), and a `content_path` JSON pointer. Entry sections additionally
record zero-based `entry_indexes` into that section's canonical entries, avoiding duplicate evidence.
Template `presentation.subsection_titles` controls headings such as Sequence Implementation and
Scoreboard Implementation; unknown kinds receive readable title-case names. Entry groups follow first
occurrence, with RTL-driven coverage last. Markdown/HTML render those subsections with bold semantic
level-three headings and bullets or the existing check/coverage tables. Register row metadata also
describes Description and Fields detail subsections. No model call is needed for this formatting step.
Interface tables use the same JSON properties for every group: `name`, `width`, `direction` (DUT-relative),
`active_level`, `availability`, and `description`, with source quote/location and a `documented` boolean
map for those properties. Active level/edge applies to control signals and clocks regardless of whether
their peer is internal or external; data/address signals use `not_applicable` (shown as —).
Availability is a source-stated build/define/mode condition; blank means not specified, not proven unconditional.
In the HTML register map, click a register row (or activate its register-name button with the keyboard)
to expand its description and field subtable. Clicking it again collapses it; opening another register
closes the previous one. Printed reports and no-JavaScript views include all details. Markdown retains
the same descriptions and field tables with pairing markers for HTML rendering. Missing descriptions
or fields are explicitly reported as not recovered from the specification.
Table source cells show an evidence indicator only. Its tooltip includes a one-line source excerpt,
inference reason where applicable, and links to the reference evidence. These compact excerpts are
deterministic excerpts, not new model interpretations; the evidence index saves source summaries in JSON.

Provenance follows a shared source-support rule across generators and claim checking: direct statements
and unambiguous factual normalizations with no added assumptions are DOCUMENTED (for example,
slave → responder, or an explicit enable bit → configuration control). Added architecture choices,
hypotheses and assumptions beyond source facts are INFERRED, with reasoning; unsupported claims are
ASSUMED. Interfaces classify group properties separately, and strategy classifies environment,
agents, sequences/checks, scoreboards, register model and virtual sequences individually. New
DOCUMENTED classifications require an exact supporting source quote; matching a quote establishes
traceability, while semantic support still relies on generation/claim checks and human review.
No extra classification API pass is added. A policy marker invalidates old final/step caches;
changed prompts/schemas invalidate affected raw response checkpoints. Unvalidated RTL evidence stays
INFERRED pending RTL engineer validation under the existing authority guards.
If no specification document exists, or the prompt explicitly asks for a
specification from RTL, `/plan` first creates an [RTL-derived specification draft](RTL_SPECIFICATION.md).
Every claim and downstream check from that draft stays `INFERRED` and `NEEDS_REVIEW`
until an RTL engineer validates a separate approved specification. `/code` is
blocked for an unvalidated RTL-derived plan.
The interactive terminal has five commands:

| Command | Action |
| --- | --- |
| `/plan` | Ingest specifications, or draft one from RTL with inferred authority; build graphs, recover registers/configurable controls, and write `testplan_doc.json`, editable Markdown and readable HTML. |
| `/code` | Generate `/plan` if needed. With a configured model, design/review a documented-source implementation contract, incrementally render reusable UVM components; defer compilation to `/run` or `/regress`. Without a model or explicit code contract, retain the labeled legacy smoke scaffold. |
| `/code demo` | A connectivity-only testbench that still simulates, built without a model; see [DEMO_TESTBENCH.md](DEMO_TESTBENCH.md). |
| `/run` | Execute the first built test with local Xezim; functional UVM tests require UVM sources and real checking/coverage evidence. |
| `/regress` | Execute all tests in the current code manifest and retain per-test/seed logs and coverage. |
| `/fresh` | Start over: new run directory, no cached state reused. The earlier run is kept for review. Saying "start fresh" works too. |

Beyond the commands, the terminal answers adjacent free-text asks instead of
only scanning repositories: "why did it fail" explains the review, "show
interfaces/registers/strategy/testplan" summarizes saved artifacts, "validate
flow.json" checks a flow file, "status" reports the run, and "rerun registers"
re-executes one step. Reruns execute a single registry tool through the same
never-do guards as the flow (unknown tools and out-of-directory or RTL-tainted
arguments are blocked); code generation stays behind `/code` with its
documented-only policy. `run --fresh` clears cached and derived state in
`--out` (refusing directories without run markers) and reruns.

`/plan` requires `MODEL_API_KEY`. `/run` and `/regress` need a local `xezim`
executable on `PATH` or `XEZIM_BIN` set to its full path. A missing simulator
or plan reports BLOCKED; it never reports a simulated PASS. Functional simulation
also requires `XEZIM_UVM_DIR` pointing to a UVM source release. The legacy smoke
test does not claim functional correctness. See [CODE_GENERATION.md](CODE_GENERATION.md)
for contracts, templates, supported behaviors, recovery and current validation limits.
Saved functional projects can also be replayed without a model using
`dv-agent run-code --out <run>` or `dv-agent run-code --out <run> --regress`.
`/code` saves dependency notes and each unit’s pseudocode before implementing that unit;
final collation follows incremental translation. These are indexed by `<run>/code_work_manifest.json`; standalone
`dv-agent plan-code --out <run>` stops at pseudocode. See [work packages](CODE_WORK_PACKAGES.md).
Ctrl-D leaves the terminal. The
advanced non-interactive CLI below remains available for custom flow files.

As soon as `/plan` saves the report, the terminal opens a loopback-only viewer
on an available port and prints its URL, the polished HTML file path and the
editable Markdown path. The viewer lists all generated plans under `runs/`.
Keep the orchestrator terminal open while using the URL. If local port binding
is unavailable, the HTML file remains readable directly.

### Warning before code

`/code` starts without a confirmation step, because code is built only from DOCUMENTED plan entries that cite a
specification source. First it prints what will and will not be used (used vs inferred, assumed, uncited and RTL
observation entries; DV-agent methodology rules are not used as code facts; lineage note when entries cite chunks
only). On a real terminal it then waits `DV_AGENT_CODE_ABORT_SECONDS` seconds (default 10, 0 disables) for `/abort`;
Ctrl-C stops it at any time. Piped or scripted sessions do not wait. Generated code stays NEEDS_REVIEW.

## Advanced CLI

```sh
# Check a flow without running it
.venv/bin/python -m orchestrator_agent validate \
  --flow src/orchestrator_agent/flows/default_flow.json

# Dry run: resolve arguments, run every guard, execute nothing
.venv/bin/python -m orchestrator_agent run \
  --flow src/orchestrator_agent/flows/default_flow.json \
  --out runs/orch_uart --repo ../baseline_repos/uart16550 \
  --rtl-files ../baseline_repos/uart16550/rtl/uart.v --rtl-top uart \
  --clock wb_clk_i --llm off --dry-run

# Real run (LLM decider only when MODEL_API_KEY is set; --llm off walks the order)
.venv/bin/python -m orchestrator_agent run \
  --flow src/orchestrator_agent/flows/default_flow.json \
  --out runs/orch_uart --repo ../baseline_repos/uart16550 \
  --rtl-files <files...> --rtl-top <top> --clock <clk>

# After a NEEDS_REVIEW stop: inspect, then resume with approval
.venv/bin/python -m orchestrator_agent status --out runs/orch_uart
.venv/bin/python -m orchestrator_agent run --flow ... --out runs/orch_uart \
  --repo ... --approve <step-id>
```

Exit codes: `0` PASS, `3` NEEDS_REVIEW (owner gate), `1` BLOCKED (flow/config
fault), `2` usage error.

`/plan` shows a live three-pane dashboard on interactive terminals. The right
pane lists graph steps and each testplan substep; the middle shows an overall
progress bar, current task name, task progress checkpoints, start timestamp and
elapsed time updated when a task completes. The left shows tool-call budgets and observed tokens. A
non-TTY session gets a plain event log with the same substep events. The
non-interactive `run` CLI keeps pure JSON stdout and no dashboard.

## Flow JSON

`src/orchestrator_agent/flows/default_flow.json` is the starting point: spec
ingest/graph, RTL port extraction and graph, spec interface/register/strategy/
testplan (the RTL graph feeds only the opt-in review-required observations
section), then the UVM scaffold behind an owner review gate.

Steps, in recommended order:

| Field | Meaning |
|---|---|
| `id` | Unique step name (`[a-z0-9_]+`); used by `--approve` and revisits |
| `tool` | One of the registry tools (see below); unknown tools fail closed |
| `agent` | `dv` or `rtl`; must match the tool's owner |
| `args` | Tool arguments; `${name}` placeholders come from CLI options/`--var`, `${name:-default}` applies when unset |
| `optional` | May be skipped by the decider or on failure (default `false`) |
| `review_gate` | Owner must `--approve <id>` before it runs (default `false`) |
| `allow_extra_prompt` | Decider may attach a follow-up question on revisit (default `true`) |
| `timeout_s` / `max_attempts` | Per-step overrides of the policy defaults |

CLI variables: `--repo`, `--include` (repeatable list), `--rtl-files`
(repeatable list), `--rtl-top`, `--scope`, `--template`, `--clock`, `--reset`,
`--reset-active`, `--agent-args`, plus `--var NAME=VALUE`. `${out}` is always
the run directory. A sole `${list}` placeholder keeps its type.

Registry tools: `dv_ingest`, `dv_build_graph`, `dv_interfaces`, `dv_registers`,
`dv_strategy`, `dv_testplan`, `dv_context`, `rtl_extract`,
`rtl_build_interface`, `rtl_build_graph`, `rtl_query`, `uvm_build`. The `dv_*`
wrappers call `dv_agent.pipeline`, the `rtl_*` call `rtl_agent`, and
`uvm_build` calls the UVM generator (offline unless `llm: "on"` with a key).

## Strict never-do list

`forbidden` is mandatory and must include `NO_RTL_INTO_UVM`. Unknown rule IDs
fail the run closed. Guards never call the model.

| Rule | Enforcement |
|---|---|
| `NO_RTL_INTO_UVM` | `uvm_build` takes only the interface JSON, test plan and agent args. `rtl_*` arguments, RTL-tagged files and RTL-excerpt markers in follow-up prompts are blocked. Port inventories (`INTERFACE`) are wiring facts and allowed; graph facts, excerpts and bundles (`RTL_BEHAVIOR`) are not. Expected behaviour stays spec-authoritative. |
| `NO_RTL_AS_SPEC_AUTHORITY` | RTL observations must stay `INFERRED` + `NEEDS_REVIEW`; follow-up prompts may not approve them. Checked after the testplan step. |
| `NO_DESIGN_MUTATION` | Every tool output must stay under `--out`, which must differ from the source repo. Sources are read-only. |
| `NO_SPEC_FLOW_CONTAMINATION` | Spec-only steps take no `rtl_*` input; only the testplan's explicit `rtl_graph` is allowed. |
| `NO_NEW_TOOLS` | The decider names only flow steps; invented tools or reorderings are rejected. |
| `NO_MANDATORY_SKIP` | Only `optional: true` steps may be skipped. |

## Decider, loops, timeouts, owner gates

After each passing step (real runs with an LLM only), the decider answers
`orchestrator_next` with one action: `continue` (default), `revisit` a
completed step with `extra_prompt`, `skip_optional`, or `stop`. Retrieval
tools (`dv_context`, `rtl_query`) append the follow-up question to the query;
other tools record it in the trace and re-run. Invalid or forbidden proposals
are logged and ignored; the recommended order continues.

| Budget / gate | Policy key | On exhaustion |
|---|---|---|
| Attempts per step | `max_attempts_per_step` (2) | Owner review; approve to run again |
| Revisits per step | `max_revisits_per_step` (1) | Further revisit proposals rejected |
| Total overrides | `max_overrides` (3) | Further overrides rejected |
| Rejected decider proposals | `> max_overrides` | Owner review (nagging decider) |
| Total tool calls | `max_total_tool_calls` (32) | Owner review (possible loop) |
| Per-step timeout | `timeout_s` / `default_step_timeout_s` (600s) | Step TIMEOUT, then attempts/owner. Not applied to `dv_build_graph` and `dv_testplan`, which run until the global timeout |
| Global timeout | `global_timeout_s` (3600s) | Owner review. Also stops a running model stage: at the deadline it starts no new model calls, keeps what it saved, and the run reverts to the owner |
| `review_gate` step | `--approve <id>` | Run pauses until approved |

Each run writes `orchestrator_trace.jsonl` (every tool call, guard check,
decider proposal and budget event), `orchestrator_result.json` (per-step
status, counters, violations) and, on any non-PASS finish,
`orchestrator_review.json` with the reason, the question for the owner, the
pending step and an exact resume command. Resuming re-runs the same command
with `--approve`; underlying stages reuse their on-disk outputs, and the
approval grants a fresh budget round.

## Limitations

- A step timeout stops waiting, not the worker thread, which lingers until
  the tool returns; there is no subprocess isolation or hard kill yet.
- Counters restart on an approved resume by design; the approval is the
  permission to run again.
- Live behaviour (model decider, LLM-backed DV steps, embeddings) needs
  `MODEL_API_KEY` and is NOT_RUN in offline tests.


During a retry the progress display retains the previous failure, for example
`BLOCKED/RETRY(1)`, `FAIL/RETRY(2)` or `TRANSIENT/RETRY(1)`. This appears beside
the task and in the current-task panel; plain terminals receive the same label.
Retrying tasks remain incomplete for percentage calculations. Completion replaces
the temporary retry label with the actual result. Tool retries, model transport
retries and code-planning repairs report this state. On reopening the same run,
saved progress traces restore failure/retry history. A successful task revisit
is displayed as a normal run rather than as a failed-task retry.

Basic binding ambiguities now enter **WAITING_HUMAN** through an explicit
[human-in-the-loop workflow](HUMAN_REVIEW.md). After a configurable terminal wait,
Hermes requests a human Telegram acknowledgement. Only explicit human approval
updates the versioned testplan, with visible approval comments, before code resumes.
Timeouts and Hermes advice never authorize a binding. Telegram target, allowed user
IDs and the supplied gateway plugin must be configured for remote escalation.

Clock frequency/period planning, reviewed settings and seeded per-band campaigns are documented in [Clock timing](CLOCK_TIMING.md).
