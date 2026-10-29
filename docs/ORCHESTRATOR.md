# Orchestrator agent

`orchestrate-agent` runs the DV agent and the RTL agent step by step from a
**flow JSON contract**: the recommended tool order, the execution budgets, and
a strict never-do list. Without a model it walks the recommended order; with
one, a bounded decider may revisit a completed step with a sharper follow-up
question, skip an optional step, or stop. Every budget exhaustion, timeout,
rule violation and review gate reverts to the owner with a review file and a
resume command.

## Interactive testplan flow

Run `.venv/bin/orchestrate-agent` from this repository and describe the local
design repository in one sentence, for example:

```text
orch> Generate a UART16550 verification testplan from its specification and RTL.
```

The terminal scans the named repository without writing to it, identifies the
specification documents and RTL top, and immediately prints the steps it will
run in English. The testplan step expands into interface isolation, register
recovery, every section from the template, and Markdown/HTML rendering.
The interactive terminal has four commands:

| Command | Action |
| --- | --- |
| `/plan` | Ingest specifications, build spec and RTL graphs, recover registers/configurable controls, and write `testplan_doc.json`, editable Markdown and readable HTML. |
| `/code` | If no plan exists in this session, run `/plan` first. Build a UVM scaffold from cited `DOCUMENTED` plan items only; exclude inferred/uncited items and RTL observations. Also build one basic compile/clock/reset smoke test. |
| `/run` | Run the basic built smoke test with local Xezim and save its log/result. |
| `/regress` | Run every executable test listed in the code manifest and save results. Currently `/code` builds one smoke test; protocol-specific functional tests still need reviewed implementation. |

`/plan` requires `MODEL_API_KEY`. `/run` and `/regress` need a local `xezim`
executable on `PATH` or `XEZIM_BIN` set to its full path. A missing simulator
or plan reports BLOCKED; it never reports a simulated PASS. The smoke test
does not claim functional correctness. Ctrl-D leaves the terminal. The
advanced non-interactive CLI below remains available for custom flow files.

As soon as `/plan` saves the report, the terminal opens a loopback-only viewer
on an available port and prints its URL, the polished HTML file path and the
editable Markdown path. The viewer lists all generated plans under `runs/`.
Keep the orchestrator terminal open while using the URL. If local port binding
is unavailable, the HTML file remains readable directly.

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
| Per-step timeout | `timeout_s` / `default_step_timeout_s` (600s) | Step TIMEOUT, then attempts/owner |
| Global timeout | `global_timeout_s` (3600s) | Owner review |
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
