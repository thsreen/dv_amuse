# Review and current status

Reviewed `main` at `bad38bd` and its recent changes. The initial working tree was clean. Baseline:
`.venv/bin/python -m pytest -q` — **155 passed, 2 deselected**. The latest commit adds combined graph
fetch and token accounting; earlier recent commits add refuse-and-repair and specification steps.

## Findings and proposed changes

1. **P1 — citation existence does not establish claim support.** `ingest/extract.py::_apply_extraction` and
   section validation check source spans/IDs, but a valid quotation can accompany an unsupported
   restatement. Add the already-planned independent claims check per section through `quality/repair.py`.
   Keep unsupported interpretations `NEEDS_REVIEW` and test an exact quote paired with a contradictory
   claim. This is still an open implementation gap, not an observed live model failure.

2. **P1 — live integration remains unverified in dv_agent.** Offline mocks do not establish compatibility
   with the configured Meta structured-output contract, embeddings or Langfuse. The reference project's
   older live evidence does not validate this client's later changes. Run the opt-in live suite and one
   complete traced pipeline with credentials; save request IDs, validation failures and token usage.

3. **P2 — scoped plans can be forced to cite unrelated requirements.**
   `plan/testplan_doc.py::_add_coverage_targets` computes coverage over the entire graph and appends those
   requirements without a scope boundary. Reproduced directly with a context containing only block 1:
   targets included both block 1 and block 2. Define an explicit in-scope requirement set and apply it
   consistently to fetch, coverage targets and the final denominator. Add a two-block regression case.

4. **P2 — the path length filter can discard an available bounded path.**
   `retrieval/combined_fetch.py::target_paths` finds an unconstrained minimum-weight path, then filters its node
   count. Reproduced with a direct `a→d` edge of weight .5 and a three-edge alternative of .99 per edge:
   `max_length=3` returned no path, although the direct path fits. Use hop-bounded search, or choose
   shortest-hop paths and break ties by weight. Count `max_targets` after rejecting unusable targets.

5. **P2 — requirement/dependency extraction still drops refused output without repair.**
   `ingest/extract.py` has not adopted the repair mechanism used by the later steps. Apply bounded repair to
   these two extraction calls, with explicit questions when the budget is exhausted.

These changes are proposed follow-ups; this session implements the user-requested RTL coding flow
without changing the specification-only pipeline or mixing its evidence with design declarations.

## Capability status

| Capability | Status |
|---|---|
| Specification ingestion, graph construction/retrieval, specification interfaces/registers/strategy and templated plan | PASS in offline tests |
| Combined fetch, dependency ordering, citation accounting, token reporting | PASS in offline tests; retrieval benefit on a real LLM graph unmeasured |
| Meta API, embeddings and Langfuse integration in current code | NOT_RUN live |
| Independent claim support checks, review/sign-off command | Pending |
| RTL declaration extractor and basic JSON interface builder | Implemented; isolated coding flow, offline tests and three reference-checked UART configurations |
| Optional SV export | Generated and unit-checked; compilation/simulation NOT_RUN |
| Design verification/sign-off | NEEDS_REVIEW; no behavioral verification claimed |

## Implemented changes

- New `rtl_agent` package: bounded preprocessing, explicit module selection, parameter/bound resolution,
  source-backed extraction, JSON template builder, optional SV export from original RTL, safe artifact writes.
- Commands: `rtl-interfaces` and `build-interface`. Default builder output is `interface_definition.json`;
  SV export is opt-in with `--emit-sv`.
- Basic template: `src/rtl_agent/templates/rtl_interface_v0.json`, inspired by the legacy source manifest.
- Unsupported selected declarations fail explicitly; no guessed widths or protocol behavior. Saved
  JSON is a compact wiring inventory; re-extract after source changes. Design sources remain unchanged.
- Usage, supported syntax, resource limits, examples and reference validation: `docs/RTL_INTERFACES.md`.

The recommended next hackathon work is the independent claims check, followed by a complete live run.
For broader RTL syntax, replace/extend the bounded declaration frontend behind the same JSON contract
once a full parser can be installed and tested. Keep both flows independent.

Validation after implementation: `.venv/bin/python -m pytest -q` — **210 passed, 2 deselected**;
`git diff --check` — PASS. Three UART configuration inventories matched the legacy reference;
all 12 original RTL-file hashes remained unchanged. Work is uncommitted.

User-requested simplification: both saved interface JSON files now contain only sources (top basename), DUT-relative directions, uppercase name/width parameters, and name/direction/width-or-bounds ports. Groups are included only when supplied. Metadata, hashes, signedness and per-item sources are omitted. The parser retains its working details internally.
