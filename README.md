# Silicon Copilot

Silicon Copilot turns a design repository's specifications and RTL into a traceable verification
plan, generated SystemVerilog/UVM collateral, and simulation results. The interactive orchestrator
coordinates specification analysis, RTL analysis and code generation through four main commands:
`/plan`, `/code`, `/run` and `/regress`.

Meta's Muse Spark model interprets specification evidence, proposes verification plans and implements
bounded code-generation work packages. Reusable templates provide the testbench structure, while
validation, source citations and simulator results expose unsupported or incomplete output.

Specifications define intended behavior. Configured RTL supplies physical interface information;
source references, deterministic checks and review decisions connect the two. Generated collateral
requires engineering review.

![End-to-end architecture](docs/architecture/end_to_end.svg)

> **Diagram legend:** 🟪 **Purple blocks** in the flowcharts indicate steps that use an LLM or make model API calls.

## Quickstart

Run these commands from the repository root. Python **3.11 or newer**, Git and access to the
configured model API are required for the model-backed workflow.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
cp .env.example .env
```

Set `MODEL_API_KEY` in `.env`, then start the terminal:

```sh
.venv/bin/python -m orchestrator_agent --mode basic
```

Describe the design repository and any required build options. For example, if the UART baseline
is available in a sibling directory:

```text
Verification collateral for the 8 bit UART in ../baseline_repos/uart16550
```

Then enter:

```text
/plan
/code
/run
/regress
```

The UART baseline is an example input and is not bundled with this repository. You can provide
another local design repository with its specifications and supported RTL sources.

| Command | Result |
|---|---|
| `/plan` | Generates the cited testplan for the selected design/configuration, with JSON, Markdown and HTML copies. |
| `/code` | Generates interfaces and verification components in bounded work packages, with dependency notes, pseudocode and validation records. |
| `/run` | Compiles the generated code and simulates the first built test. Requires Xezim and UVM. |
| `/regress` | Compiles and runs all built tests. Requires Xezim and UVM. |

`/code` can restore the latest compatible successful saved plan. If no suitable plan exists, it
starts planning for the selected repository. `/fresh` starts a fresh session. `/run wave` additionally
records an FST waveform; delivery to Telegram requires notification configuration.

Basic mode uses lexical retrieval and is the default. Use `--mode graph` to select the graph-based
workflow. See [orchestrator commands and recovery](docs/ORCHESTRATOR.md).

## Quick testing and demos

Normal operation uses human review for unresolved decisions. To enable the temporary, isolated
quick-testing workflow explicitly:

```sh
.venv/bin/python -m orchestrator_agent --mode basic --quick-testing-auto-approve-inferences
```

This copies the plan into a separate run, approves inferred content for testing, and evaluates
infrastructure clarifications automatically. Approvals retain inferred provenance and test-only
labels. Quick testing can defer unsupported features, set aside generated tests or hooks, and
select a script-built bring-up test. Review the generated summary to see what was actually built.

**Recorded result:** the published 8-bit UART16550 example passed `quick_basic` on real RTL with
two scoreboard comparisons, 37 passing assertions and zero UVM errors. This is a bounded
quick-testing result, not evidence that every generated scenario or the complete design passes.
Inspect the [saved testplan and logs](review_artifacts/run_20261104_8bit_pass/),
[current capability status](docs/CODE_REVIEW_STATUS.md), and [quick-testing limits](docs/QUICK_TESTING.md).

## Review artifacts

**Reviewers: start with the [saved 8-bit UART run](review_artifacts/run_20261104_8bit_pass/).**
This checked-in snapshot holds the plan, generated testbench, coverage, waveform and logs from November 4, 2026, so you can
inspect the recorded result without API credentials or a simulator installation. Its
[guide](review_artifacts/run_20261104_8bit_pass/README.md) lists the results, the limits and how to reproduce the test.

| Suggested order | Artifact | What to check |
|---|---|---|
| 1 | [Testplan: Markdown](review_artifacts/run_20261104_8bit_pass/test_plan/testplan_doc.md) / [HTML](review_artifacts/run_20261104_8bit_pass/test_plan/testplan_doc.html) | Strategy, register map, planned tests, inference labels and open questions. Download the HTML and open it in a browser for the formatted view. |
| 2 | [Structured testplan](review_artifacts/run_20261104_8bit_pass/test_plan/testplan_doc.json) | Machine-readable sections, source references and review metadata. |
| 3 | [Planning trace](review_artifacts/run_20261104_8bit_pass/logs/plan_trace.jsonl) and [code-generation trace](review_artifacts/run_20261104_8bit_pass/logs/code_trace.jsonl) | Stage progression, retries, approvals, deferrals and recorded completion. |
| 4 | [Compiler log](review_artifacts/run_20261104_8bit_pass/logs/compile.log) | Parsing/elaboration outcome and compiler warnings. |
| 5 | [Simulation log](review_artifacts/run_20261104_8bit_pass/logs/simulation.log) | `FUNCTIONAL_TEST_PASS quick_basic`, two scoreboard comparisons and zero UVM errors/fatals. |
| 6 | [Coverage report](review_artifacts/run_20261104_8bit_pass/results/coverage_report.md) and [waveform](review_artifacts/run_20261104_8bit_pass/results/quick_basic.fst) | What the one test sampled; open the FST in GTKWave or Surfer |
| 7 | [Generated testbench](review_artifacts/run_20261104_8bit_pass/testbench/) and [design records](review_artifacts/run_20261104_8bit_pass/design/) | SV and UVM sources, review objections, test-only approvals and what was set aside |

It records one quick-testing configuration and its script-selected test;
the complete testplan and all model-proposed scenarios have not thereby been verified. Check
[current status and limitations](docs/CODE_REVIEW_STATUS.md) alongside the logs. Runtime outputs
from your own runs remain under the ignored `runs/` directory.

## Simulation setup

Planning and code generation do not require a simulator. `/run`, `/run wave` and `/regress` require:

- A working Xezim executable, available on `PATH` or selected by `XEZIM_BIN`.
- UVM sources selected by `XEZIM_UVM_DIR`, containing `uvm_pkg.sv` and `uvm_macros.svh`.

The repository includes an installer for the pinned UVM source release:

```sh
.venv/bin/python tools/install_uvm.py
```

The installer downloads UVM and updates the local `.env`. Set the simulator path there if needed:

```dotenv
XEZIM_BIN=/absolute/path/to/xezim
XEZIM_UVM_DIR=.deps/uvm-core-2020.3.1/src
```

`tools/xezim` and `tools/e2e_sim` are optional submodules. Initialize only those you need, for example
`git submodule update --init tools/xezim`; initialization alone does not build the simulator.
See [code generation and local simulation](docs/CODE_GENERATION.md) or
[optional cloud simulation](docs/E2E_SIM.md) for setup details.

## Configuration

Copy configuration from [.env.example](.env.example); keep credentials in the ignored `.env` file.
Existing environment variables take precedence over that file.

| Setting | Purpose |
|---|---|
| `MODEL_API_KEY` | Credentials for model-backed planning and generation. |
| `META_MODEL`, `META_BASE_URL`, `META_API_STYLE` | Model, compatible API endpoint and request style. |
| `META_REQUEST_TIMEOUT_SECONDS` | Per-request timeout; default 150 seconds. |
| `DV_AGENT_LLM_MODE` | `auto`, `on` or `off`; `auto` enables model use when credentials are configured. |
| `XEZIM_BIN`, `XEZIM_UVM_DIR` | Local simulation dependencies. |

`--llm off` supports structural/offline operations; it does not provide the complete model-backed
verification workflow. Output allowances scale with input size; retries and semantic repair are
bounded. Changed inputs can invalidate checkpoints, so cache reuse does not guarantee a zero-call run.

Tracing is local by default. Optional Langfuse configuration mirrors metadata; sending prompt/source
content requires `LANGFUSE_CAPTURE_CONTENT=1`. Configuring Telegram can enable startup messages,
testplan delivery and waveform delivery; these artifacts may contain specification or design data.
See [human review and notification configuration](docs/HUMAN_REVIEW.md).

## Plans, interfaces and generated artifacts

The default testplan has 13 sections, including feature description, register map, RTL observations,
verification strategy, implementation plan, stimulus, checks, coverage and designer questions.
The structured JSON preserves citations and provenance. Markdown supports editing, and HTML is
rendered from that same Markdown.

To refresh an edited report without model calls:

```sh
.venv/bin/dv-agent render-testplan --out runs/<run>/dv
```

To browse generated plans and use the **Render testplan** button:

```sh
.venv/bin/dv-agent render-testplan --serve
```

Open the printed local URL. The viewer defaults to port 8765; use `--port` to change it.
See [Markdown feedback and review](docs/REPORT_FEEDBACK.md) for structured human feedback.

The code-generation path compares independently extracted spec and RTL ports and independently
validates the comparison before consuming the bindings. Interface directions are relative to the DUT:
drivers own DUT inputs; monitors observe inputs and outputs; clock/reset use common UVCs. Driver
reset functions initialize owned inputs without adding competing tie-offs.

| Run artifact | What to inspect |
|---|---|
| `dv/testplan_doc.json`, `.md`, `.html` | Structured plan and editable/readable views. |
| `rtl/interface_definition.json` | Compact configured RTL port inventory. |
| `interface_port_comparison.*`, `interface_port_validation.*` | Spec/RTL reconciliation and independent validation. |
| `code_work/`, `CODE_EXECUTION_PLAN.md` | Per-unit context, dependency planning, pseudocode and checkpoints. |
| `code_manifest.json`, `code/<build-id>/` | Generated source inventory, tests and implementation files. |
| `code_result.json`, `code_trace.jsonl` | Generation outcome and progress. |
| `code/<build-id>/compile_result.json`, `simulation/` | Compilation and simulation evidence. |

Orchestrator runs are written under `runs/`; individual `dv-agent` commands may use a different output
root. Generation completion, compilation, simulation and engineer approval are separate outcomes.
Always inspect their respective status records. `BUILT_NEEDS_REVIEW` does not mean simulation passed.

## Lower-level tools

The installation provides `dv-agent`, `rtl-agent`, `orchestrate` and `orchestrate-agent` commands in
`.venv/bin/`. For example:

```sh
.venv/bin/dv-agent ingest /path/to/design --out runs/my_design
.venv/bin/dv-agent build-graph --out runs/my_design
.venv/bin/dv-agent query "reset behavior" --out runs/my_design
.venv/bin/dv-agent testplan --out runs/my_design
.venv/bin/python -m rtl_agent --help
```

These are separate CLI invocations; the slash commands above belong inside the orchestrator terminal.
The standalone `rtl_agent` extractor, interface builder and RTL graph tools can be used independently.
The explicit RTL-observation section remains inferred until reviewed by a design engineer.

## Development and reference

Run the offline suite:

```sh
.venv/bin/python -m pytest -q
```

Real simulator acceptance tests require the dependencies above and an explicit opt-in:

```sh
DV_AGENT_TEST_SIMULATION=1 .venv/bin/python -m pytest -q tests/test_codegen.py -k real_uart
```

| Topic | Documentation |
|---|---|
| Architecture and retrieval | [Architecture](docs/ARCHITECTURE.md), [workflow internals](docs/WORKFLOW.md) |
| Coding stages and templates | [Code generation](docs/CODE_GENERATION.md), [work packages](docs/CODE_WORK_PACKAGES.md) |
| RTL configuration and interfaces | [Request configuration](docs/RTL_CONFIGURATION.md), [interface extraction](docs/RTL_INTERFACES.md), [comparison gate](docs/INTERFACE_PORT_COMPARISON.md) |
| RTL graphs and inferred specifications | [RTL Graph-RAG](docs/RTL_GRAPH_RAG.md), [RTL observations](docs/RTL_OBSERVATIONS.md), [RTL-derived specifications](docs/RTL_SPECIFICATION.md) |
| Reusable verification infrastructure | [Common UVCs](docs/COMMON_UVC_FLOW.md), [driver defaults](docs/DRIVER_IDLE_VALUES.md), [register access](docs/REGISTER_WRITE.md) |
| Governance | [Human review](docs/HUMAN_REVIEW.md), [protected files](docs/PROTECTED_FILES.md) |

## License

[Apache License 2.0](LICENSE). Third-party notices are in [NOTICE](NOTICE).
