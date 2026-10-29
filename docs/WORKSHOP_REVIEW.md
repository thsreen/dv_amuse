# dv_agent vs the Meta legal-agent workshop

Review date: 2026-10-29. Workshop source: `github.com/meta-models/legal-agent-workshop` at `12d929d`
(read only; nothing from it was executed). dv_agent at `3607f8c`. Meta docs read:
`dev.meta.ai/docs/protocols/responses`, `/docs/quickstart`, `/docs/structured-output`.

## What the workshop teaches

The model runs a tool loop (one tool per turn, no scripted order). Code executes each tool and keeps a
case record of quote-checked facts. Checks sit inside the tools at fixed points
(`set_checklist`, `request_evidence`, `submit_memo`); a failing check refuses the call with feedback,
the model repairs and retries, three refusals escalate to a person. A second model call judges whether
each finding is supported by its quotes, only after the deterministic memo rules pass. A hidden ground
truth (outside the agent's folder) scores checklist coverage without leaking it. Runs save after every
turn, stop while waiting for a person (no model calls), resume, branch, and end at a human sign-off.
Documents are read through the Files API and transcribed by the model; every quote is checked against
that saved text. Offline tests drive the real OpenAI SDK through a scripted HTTP transport.

## Comparison

| Workshop element | dv_agent today | Gap |
|---|---|---|
| Model chooses tools; no hard-coded order | Fixed pipeline: ingest → graph → interfaces → registers → strategy → sections. The model does the semantic work inside each step (extraction, grouping, register records, strategy, sections, rerank, sufficiency) but never chooses the step. | **Large** for the "Meta AI tooling" criterion |
| Facts carry exact, checked quotes | Requirements, signals, register records and fields are checked against chunk text; exact offsets and pages kept | Matches |
| Cite only recorded facts | Citations outside the supplied evidence are dropped; DOCUMENTED/INFERRED without citations become ASSUMED | Matches |
| Evidence separate from interpretation | `status` (DOCUMENTED) vs `interpretation` (INFERRED) on requirements; per-entry provenance tags | Matches |
| Check fails → refusal with feedback → model repairs | Checks run, but the code silently drops or downgrades bad output; the model never sees the problem or repairs it | **Large**: no visible repair, which the demo needs |
| Claims check by a separate model call | None; the model's own entries are only checked deterministically | **Medium** |
| Escalate after repeated refusals; human request for missing evidence | Designer questions are collected in the plan; the run never stops for a person | **Medium** |
| Human sign-off; rejection notes go back to the agent | Everything is `NEEDS_REVIEW`; no approve/reject command and no revision loop | **Medium** |
| Hidden ground truth for coverage | `eval/uart_cases.json` measures retrieval and is inside the repo; nothing scores interface, register or test-plan coverage | **Medium** |
| Save every turn, resume, branch | Stage-level reuse, `--force`/`--fresh`, response cache; no turn-level state (there is no loop) | Small today; grows with an agent loop |
| Files API + model transcription (scans, tables, figures) | pypdf, DOCX and HTML text only; diagrams and image-only pages are lost | **Medium** for real specs (bit-field and timing diagrams) |
| Client: SDK retries (4, honours Retry-After), 180 s timeout, `MODEL_API_KEY`/`MODEL_API_BASE_URL`/`MODEL_API_MODEL` | Own retry loop (3 attempts, fixed backoff, ignores Retry-After), 90 s timeout, `META_BASE_URL`/`META_MODEL` | Small; align |
| JSON mode (`text.format = json_object`) + parsing in code | Strict `json_schema` everywhere. Meta documents `json_schema` (examples omit `strict`); the workshop never relies on it | **Risk**: unverified live |
| `openai>=2,<3` | `openai>=2`, 3.40 installed | Risk: untested major version |
| Offline tests through the real SDK (scripted transport) | Fake client objects bypass the SDK, so request-shape errors would not be caught | Small |
| Agent Console (turns, refusals, sign-off) | Langfuse traces + `trace.jsonl` + Markdown; no Langfuse keys yet | Small (Langfuse can be the console) |
| Case-agnostic code | Design-agnostic: no UART names in code, prompts or templates | Matches |

## Hackathon gates and rules (from META_EXPECTATIONS.md)

- **Public repository**: `thsreen/dv_amuse` is private. Must change before submission.
- **Genuine Meta model use**: not yet shown. Nothing has run live; the API contract is unverified.
- **Anti-project "basic RAG applications"**: dv_agent's retrieval core is RAG. The pitch and demo
  must lead with what is not basic RAG: model-built interface groups, register map and strategy,
  checked against the specification, with refusals, repairs and human sign-off.
- **Deadline** (reported): November 4, 9:00 PM ET.

## Recommendations, in order

1. **Run live.** Add the key, run `pytest -m live`, then the UART pipeline end to end. Confirm
   `text.format` with `json_schema` + `strict`; if it is refused, use the fallback in item 4.
2. **Refuse and repair.** At each step (interfaces, registers, configurations, strategy, test-plan
   sections) turn the existing deterministic findings into feedback sent back to the model for up to
   2 repair attempts, then record what remains as designer questions. Log every refusal and repair
   in the trace. This is the workshop's central pattern and the clearest demo moment.
3. **Claims check.** One separate model call per section judges whether each DOCUMENTED or INFERRED
   entry is supported by its cited quotes, after the deterministic checks pass. Unsupported entries
   are refused back to the author call (item 2), never self-approved.
4. **Structured-output fallback.** `META_OUTPUT_MODE=json_schema|json_object`: in `json_object` mode,
   describe the schema in the instructions and validate the result in code (types, required keys,
   enums), refusing invalid output with feedback.
5. **Human sign-off.** `dv-agent review --approve | --reject --notes "..."` on the test plan;
   rejection notes go back into the section prompts; a plan waiting for review makes no model calls.
6. **Hidden coverage check.** A golden list per specification (interfaces, registers, features) kept
   outside the repository (for example `../ground_truth/uart16550.json`), scored after each step;
   feedback names what kind of item is missing without quoting the list.
7. **Client alignment.** Accept `MODEL_API_BASE_URL` / `MODEL_API_MODEL` alongside `META_*`; use the
   SDK's retries (honours Retry-After) and a 180 s timeout; optional `reasoning.effort` (never `none`
   on Muse Spark); pin or test the `openai` major version; add a scripted-transport test through the SDK.
8. **Agent loop (larger).** Expose the steps as tools (retrieve, extract interfaces, extract registers,
   record requirement, ask the designer, write section, submit plan) and let the model choose the order,
   with the checks inside the tools. Keep the current pipeline as the deterministic baseline so the
   demo can show what the model adds.
9. **Model transcription for figures.** Files API transcription for pages with diagrams or tables
   (register bit-field figures, timing diagrams), with quotes still checked against the saved text.

Items 1-5 fit before the deadline; 6-9 depend on time.
