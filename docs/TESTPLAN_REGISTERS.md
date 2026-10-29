# Specification registers and testplan copies

The Register Map comes from specification chunks, independently of whether the
earlier requirement-extraction calls succeeded. Explicit tables with columns
`Name Address Width Access Description` (or the pipe-separated equivalent)
provide a source-quoted inventory before model enrichment. Wrapped names in PDF
text are supported. Other table layouts and prose remain the model extractor's
job; this is not a general PDF table-layout recognizer. Shared addresses stay
separate; records merge by documented names/abbreviations, not by address.

Model extraction defaults to one source window per call. Longer chunks use
overlapping windows rather than dropping everything after character 2500.
Source-table rows survive failed calls, while failures and partial status remain
visible. Unknown resets, access conditions and fields remain unknown.

The LLM classifies each register and field with `configurable` (`true`, `false`
or `null`), `configuration_reason` and a verbatim `configuration_quote`.
The verified artifact stores these under `configuration`, with INFERRED
provenance. Modes, timing, enables, masks and similar controls are distinguished
from FIFO payloads and read-only status. Unsupported classifications become
unknown; read-only access cannot become a writable configuration control.

The `configurable` list contains fields for downstream planning, including
legal encodings, addresses, access conditions, reserved handling, source IDs,
classification reasons and review flags. `identification: LLM` distinguishes
classified controls from unclassified writable `ACCESS_CANDIDATE` entries.
All need review. An inventory row whose field extraction failed is not treated
as permission to randomize the entire register. Strategy receives the register
classifications and control list; Configurations receives the individual fields.
An incomplete register extraction prevents Configurations from reporting PASS.
Extraction prompt/schema signatures invalidate stale register and plan caches.

Both Responses `max_output_tokens` exhaustion and chat `length` endings trigger
bounded budget growth: start at `META_MAX_OUTPUT_TOKENS` (default 8192), double
on token exhaustion, at most three total attempts, up to
`META_MAX_OUTPUT_TOKENS_CEILING` (default 32768). Other incomplete responses
remain failures. The trace retains response IDs, budgets, failure detail and
usage across attempts; token totals include incomplete responses that reported
usage. Partial requirement/dependency extraction reports BLOCKED, rather than
labeling the graph build PASS.

Every generated testplan has:

- `testplan_doc.json`: structured plan and evidence.
- `testplan_doc.md`: editable plan.
- `testplan_doc.html`: standalone, styled, printable view rendered directly from
  that same Markdown. No extra model call or separately authored content.

Evidence appears as compact badges in both copies: ✅ for a documented statement,
⚠️ for an inference, and 🛑 when no verified reference supports the statement.
Hover over a badge or focus it with the keyboard in HTML to see its status,
inference reason and links to the report's **Reference evidence** appendix.
The appendix records source paths, pages or RTL line numbers, and excerpts for
cited IDs. Markdown keeps the same visible content and the badge metadata in an
HTML comment so edits can be rendered back into the same tooltips. New model
output is asked to explain every inferred plan entry explicitly; legacy entries
without a reason say that designer review is needed.

After editing Markdown, refresh HTML without model access:

```sh
dv-agent render-testplan --out runs/uart16550
```

To render using a button in the HTML page, start the local viewer once:

```sh
dv-agent render-testplan --serve
```

Open `http://127.0.0.1:8765/` (or the printed URL when using `--port`). The
**Testplan** selector lists every generated `testplan_doc` under `runs/`, including
nested folders. Selecting one loads its report. Save edits to the selected run's
`testplan_doc.md`, then click **Render testplan**. It reads that plan's latest saved
Markdown, updates the displayed report and saves its `testplan_doc.html`. It leaves
the Markdown and structured JSON intact and makes no model calls. The button
shows rendering progress or an error; controls are excluded from printed output.
Ctrl+C stops the viewer. For a remote machine, forward its viewer port to your
browser machine, for example `ssh -L 8765:127.0.0.1:8765 <host>`.

Use `--out runs/uart16550 --serve` to open one plan initially while still listing
its sibling runs, or `--out <runs-root> --serve` to select plans under a different
runs directory. Reload the page to see plans created after the viewer opened.

Opening the HTML as a standalone file still displays the report. The selector
then explains how to start the viewer: browsers cannot enumerate run files or
invoke the Python renderer from a `file://` page. The viewer binds
only to loopback and serves only the selected report's HTML and Markdown.

The renderer supports the Markdown produced by the report writers: headings,
bullets, nested bullets, tables, blockquotes, fenced code and inline formatting.
Source HTML is escaped. Cached plan reuse preserves Markdown edits and refreshes
HTML; forcing a new plan regenerates both copies. Markdown review edits do not
rewrite the structured JSON consumed by later coding steps.

To regenerate the failed run with the new extraction while retaining successful
model-response caches:

```sh
dv-agent pipeline ../baseline_repos/uart16550 --llm on --testplan
```

The UART review in this session recovered 13 register inventory rows directly
from the saved specification. A focused two-chunk live check could not reach
the model API (`APIConnectionError`); the retained inventory and blocked
classification are under `runs/uart_register_review/`. Successful live model
classification and a complete regenerated plan still need validation in an
environment with API connectivity.
