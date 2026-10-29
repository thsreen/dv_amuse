# Meta Hackathon Expectations (dv_agent)

What the Meta Global AI Developer Hackathon expects, adapted for dv_agent's purely
specification-driven verification test-plan flow. Adapted on 2026-10-29 from the workspace copy
written for the earlier silicon_copilot project, after reviewing the workshop repository and Meta's
API documentation (see `docs/WORKSHOP_REVIEW.md` for the gap analysis).

Sources:

- Official event page: https://dev.meta.ai/events/global-hackathon
- Quickstart: https://dev.meta.ai/docs/quickstart
- Responses API: https://dev.meta.ai/docs/protocols/responses
- Structured output: https://dev.meta.ai/docs/structured-output
- Workshop repository: https://github.com/meta-models/legal-agent-workshop (reviewed at `12d929d`)

API and model details are official. Schedule, rubric weights and the anti-project list come from
participant notes and secondary coverage; confirm against the official rules.

## 1. Pass/fail gate

1. **Theme fit**: dv_agent fits **Build for Your World** (verification engineering is the author's
   domain) or **Push the Frontier** (a machine that turns a specification into a reviewed test plan).
2. **Genuine Meta model use at runtime**: Muse Spark must do load-bearing work in a live run.
   Status: not yet shown (no live run).

Failing either gate means the project is not scored.

## 2. Reported scoring rubric

| Criterion | Weight | What judges look for |
|---|---:|---|
| Impact | 30% | A real problem, a clear beneficiary, an outcome people could use |
| Meta AI tooling | 25% | Meta models do load-bearing work beyond a basic integration |
| Demo | 25% | A working end-to-end result that survives being recorded; the 3-minute video is primary |
| Technical depth | 20% | Sound engineering, verification, thoughtful refinement |

The workshop makes "Meta AI tooling" concrete: the model handles the ambiguous, semantic parts;
deterministic checks outside the model keep the result honest, and the model repairs what they refuse.

## 3. Reported event rules

- Public repository (dv_agent is currently private).
- At most four people; one submission per team; new work only.
- The 3-minute demo video is a primary artifact.
- Deadline: November 4, 9:00 PM ET.
- Anti-projects include **basic RAG applications**. dv_agent must present itself as a verification
  agent whose RAG layer is one tool, not as a RAG app.

## 4. Meta Model API facts that affect the code

| Item | Value |
|---|---|
| Base URL | `https://api.meta.ai/v1` (OpenAI Python SDK, `base_url`) |
| Auth | `Authorization: Bearer $MODEL_API_KEY` |
| Main model | `muse-spark-1.3` (context 1,048,576; output 131,072) |
| Endpoints | Responses (`/v1/responses`, the only one that carries reasoning across turns), Chat Completions, Messages |
| Structured output | Responses: `text.format`. Chat Completions: `response_format` with `json_schema`. `response_format` does **not** configure structured output on Responses. Documented examples omit `strict`; the workshop uses `json_object` and parses in code |
| Reasoning | Responses `reasoning.effort`, Chat `reasoning_effort`: `minimal`, `low`, `medium`, `high`, `xhigh`. `none` returns HTTP 400 on Muse Spark |
| Not implemented on Responses | `stop`, `verbosity`, `logit_bias`, `prediction`, `n > 1`, audio, `web_search_options` |
| Documents | Files API (`purpose="user_data"`) + `input_file`; images as `input_image` |
| Workshop client | SDK retries 4 (honours Retry-After), 180 s timeout, env `MODEL_API_KEY`, `MODEL_API_BASE_URL`, `MODEL_API_MODEL` |

## 5. Harness pattern to follow

- **Model reasons, code executes and records.** The model makes the semantic decisions; tools perform
  real actions and keep a record of quote-checked facts with exact locations.
- **Checks outside the model's control, at fixed points.** A failing check refuses the step with
  feedback the model can act on; the model repairs and retries; repeated refusal escalates to a person.
  The model never approves its own work.
- **Claims check.** A separate model call judges whether each claim is supported by its quotes, only
  after the deterministic rules pass.
- **Hidden ground truth.** Golden coverage data lives outside the agent's workspace and is never
  quoted, paraphrased or counted in feedback.
- **Human in the loop.** Missing evidence stops the run and asks; a waiting run makes no model calls;
  sign-off is required; rejection notes go back to the agent.
- **Saved progress.** Runs can pause, resume and be reviewed after the fact.
- **Offline tests.** Fake model or injected transport; tests never call the live API; never weaken
  tests to go green.

## 6. What this means for dv_agent

The model must do the semantic work a template cannot:

- turn specification prose and tables into requirements, interface groups and register records;
- resolve ambiguity into explicit assumptions and designer questions;
- choose which evidence a test-plan section needs and judge when it is sufficient;
- propose the verification strategy (agents, scoreboards, register model, sequences) and the
  configuration randomisation;
- repair its output when a check refuses it.

The deterministic layer must check the model, from the specification only:

- every quote is on the cited page or chunk; every citation is to recorded evidence;
- every signal, register, field and value exists in the specification text;
- every interface group has exactly one agent; agents drive only DUT inputs of their own groups;
- register map conflicts and overlaps are reported, never resolved silently;
- every writable field has a configuration entry, and legal values are specification-stated;
- nothing is reported as approved without human sign-off.

Mapping:

| Workshop | dv_agent |
|---|---|
| Case folder and documents | Design repository and its specification documents |
| `analyze_document` + quote check | Ingest + LLM extraction with quote verification |
| `set_checklist` | Interface groups, register map and test-plan outline |
| `record_fact` | Requirement, signal and register records with exact source locations |
| `request_evidence` | Designer questions (to become a run stop and resume) |
| `submit_memo` | Submit the test plan |
| `verify_memo.py` | Interface, register, configuration, strategy and citation checks |
| `verify_checklist.py` | Hidden golden coverage per specification (to add) |
| `verify_claims.py` | Claims check per section (to add) |
| Attorney sign-off | Verification-engineer sign-off (to add) |
| Agent Console | Langfuse traces + Markdown test plan |

## 7. Demo (3 minutes)

1. A specification (PDF/DOCX/HTML) a template cannot turn into a test plan.
2. The model isolating interfaces and the register map, with exact spec citations.
3. A check refusing a hallucinated signal or register value; the model repairing it.
4. The strategy: which agent drives and monitors what, and how correctness is checked.
5. Configurations with spec-stated randomisation; a register conflict raised as a designer question.
6. The claims check rejecting an unsupported entry; the repair.
7. The test plan with provenance tags; Langfuse lineage from one entry back to the spec line.
8. Verification-engineer sign-off.

If the same result appears with the model disabled (`--llm off`), the Meta AI tooling score will be
weak; show both side by side.

## 8. Definition of done

- Public repository; new work; tests run offline.
- A live run with Muse Spark produces the test plan end to end.
- Model output that fails a check is refused with feedback and repaired, visibly.
- The model cannot approve its own work; claims are checked by a separate call; a person signs off.
- Hidden coverage data stays outside the workspace and is never leaked.
- Every test-plan statement traces to an exact specification location.
- The demo runs in three minutes.
