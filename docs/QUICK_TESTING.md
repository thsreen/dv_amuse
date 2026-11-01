# Temporary approval of inferred testplan content

Start with `orchestrate --quick-testing-auto-approve-inferences`, then `/code`.
Restart an existing orchestrator to load code changes.

The switch creates an isolated sibling run and copies the selected saved testplan. Inferred items
in its sections, interfaces and register information receive `review_status: TEST_AUTO_APPROVED`,
`test_only: true` and an auditable content-bound approval record. Affected sections carry the same
review status. `provenance: INFERRED`, inference reasoning, references and original readiness statuses
are preserved. The canonical plan is not changed; this is never human or RTL engineer sign-off.

The copied JSON, Markdown and HTML include a visible approval summary. Original copied content and
receipts are saved under `quick_plan_revisions/`. Existing isolated runs are updated once; unchanged
approvals are reused. Editing approved content invalidates its approval. Turn the switch off and
these inferred items immediately cease to be eligible for coding.

Code-generation prompts and evidence validation recognize approved inferred items in this mode.
Source IDs and quotes must still validate. This does not manufacture missing evidence, mark blocked
sections complete, promote RTL-derived specifications, or bypass physical comparison, independent
validation, retrieved-item checks or other implementation checks. Thus it is not a fix for a missing
retrieved signal pointer. Runtime infrastructure clarification still uses the existing model-based
quick evaluator and keeps its own assumptions and test-only approval records.

Remove the isolated run to discard the temporary approvals. Generator source and normal plans never
depend on the copied run. This mode is intended only for quick tests and demos.

## Prototype behaviour of `/code`

Quick testing builds a prototype, so a run does not stop on what it cannot build:

- An item in a feature that does not fit the contract is deferred with the rule it broke.
- A feature with deferrals passes once 2 of its items are complete (sequences, routes, checks, coverage, hooks). Below that it is
  `DEFERRED`: what it did build stays, and the run goes on.
- A feature that cannot be completed after its repair is `DEFERRED` and not built. Reviewer objections become questions.
- `/code` reports the counts, and every deferral is in the code questions. A passing prototype is not functional sign-off.

`/code` resumes from the newest quick-testing copy of the same saved plan, also after a restart. Model answers come back from its
cache until a request differs. A new `/plan`, or `/fresh`, starts a new copy. Normal runs still stop and ask.
