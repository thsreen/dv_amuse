# Plan: code generation in small, contained steps

Status: staged implementation plan. The deterministic clock/reset binding and fixed UVC library are implemented; the broader catalog/decision-record bring-up redesign below is planned, not delivered. See [COMMON_UVC_FLOW.md](COMMON_UVC_FLOW.md).

## 1. Why the current code stage struggles

If clock and reset, the simplest part of a testbench, needed six rounds and still failed, the problem is the
shape of the work, not the model. Today one run makes about a dozen kinds of model call (interface inventory,
interface base, needs assessment, interface collateral, grouping, dependencies, pseudocode, feature,
collation, integration, review, hooks), and each call does three jobs at once:

1. **Decides** something (which protocol, which port, which check).
2. **Proves** it, by quoting the specification with a plan pointer that must be in the retrieved context.
3. **Writes a slice of one shared contract** (`CodePlan`) that later slices must agree with.

The failure modes follow from that:

- **Context grows.** Each step carries retrieved evidence, earlier answers, repair feedback and clarifications.
  The clock unit went from 11 KB to 45 KB and hit the 48,000-character cap.
- **Proof fails more often than the decision.** Quotes outside the retrieved window, unknown fact ids and
  plan pointers that drift all cause repairs, even when the decision itself was right.
- **One failure blocks everything.** Items are merged into one contract, so a bad slice stops the whole run.
- **Decisions are stored as prose** in plan sections, which the next step then retrieves as evidence.

## 2. Principles

1. **Three kinds of file, never mixed.**
   - *Library*: fixed, tested SystemVerilog UVCs (`src/dv_agent/uvc/`). Copied unchanged.
   - *Templates*: SystemVerilog with placeholders (`src/dv_agent/templates/codegen/`). Rendered.
   - *Decisions*: small typed JSON records, one per item (`decisions/<step>/<item>.json`). They are the only
     thing a model or a person produces.

   Generated code = copy(library) + render(templates, decisions). Nothing else.
2. **Deterministic first.** If the interface JSON, the plan's structured fields or a name match can decide,
   no model is called. The model chooses among options; it never writes structure.
3. **One item, one step, fixed input.** Each step sees one item (one interface, one register block, one
   stimulus entry), a fixed list of options and at most two source quotes. The budget is about 4 KB, whatever
   the size of the plan. No history, no accumulated evidence.
4. **Proof is attached, not authored.** The step's input already contains the plan item and its citations;
   the decision record points to them. The model does not write quotes.
5. **Failure has a contained scope, not a false PASS.** After two semantic attempts, checkpoint the item and ask one precise question. A required blocker stops downstream stages. Resume at the failed item without rebuilding approved decisions. Optional work outside the selected bring-up scope is explicitly DEFERRED and never counted as completed. Missing feature description/register map remain absolute blockers.
6. **A person's answer is a decision record**, read back as data, never re-asked, never fed back as evidence.

## 3. Bring-up first: a running testbench with minimal change

Bring-up needs only the interface JSON, the plan's interface groups and the register map. Each step is
deterministic or one small choice per interface.

| Step | What it decides | How | Model? | Output |
|---|---|---|---|---|
| **B0 Inventory** | Ports, widths, directions; interface groups and their roles | Interface JSON + computed roles (`plan/interface_roles.py`) | no | `decisions/inventory.json` |
| **B1 Clock/reset binding** | Clock port, reset port, reset level | Exact name match; else one question (done) | no | `decisions/infrastructure.json` |
| **B2 UVC selection** | Which library UVC each functional interface uses | The group's documented protocol name; else one choice from the catalog list (`wishbone`, `serial`, `gpio`, `passive_monitor`, `custom`) | only when undocumented | `decisions/uvc/<group>.json` |
| **B3 Role binding** | Which port plays each role of the chosen UVC | Catalog role aliases + exact/normalized name match; leftovers are one question per interface | only for leftovers | `decisions/bindings/<group>.json` |
| **B4 Agent mode** | Active or passive | Direction rule: groups the DUT only drives are passive; groups with DUT inputs are active | no | same record |
| **B5 Bring-up test** | Reset/idle first; then only safe, documented register reset reads | Register map addresses and reset values (DOCUMENTED only) | no | `tests/bringup` |

After B5: the testbench compiles, applies reset, drives idle, reads registers and checks documented reset
values. This is the minimal, reviewable first milestone, and most of it is already in the library and
templates.

Needed for bring-up, beyond what exists:

- A **`gpio` UVC** (drive/observe named single-bit or bus signals) and a **`passive_monitor` UVC** (sample and
  publish any signal set) in the library, so every interface has a home without custom code.
- A **UVC manifest** per library UVC (`uvc/<name>/uvc.json`): roles with name aliases, required roles,
  config fields with defaults, published events. The catalog is built from these files; nothing is hard-coded
  in Python.

## 4. Feature steps: one plan item at a time

Each step reads structured fields the plan already produces, chooses a template, fills its parameters, and
validates the result before rendering.

| Step | Input (per item) | Choice / parameters | Template | Model? |
|---|---|---|---|---|
| **F1 Register model** | Register map entries (address, access, reset, fields) | none | `reg_block.svh.tmpl` (RAL-lite) | no |
| **F2 Configuration** | One Configurations row (field, legal values, constraints) | Constraint kind and values | `cfg_constraint.svh.tmpl` | rarely |
| **F3 Sequence** | One stimulus entry + its quotes + register/port names + sequence catalog | Sequence kind (`write_read`, `random_access`, `config_sweep`, `traffic`, `error_inject`, `custom`) and parameters | `seq_<kind>.svh.tmpl` | yes, small |
| **F4 Check** | One check entry + quotes + checker catalog | Checker kind (`reset_value`, `read_after_write`, `route_compare`, `protocol_assertion`, `custom`) and parameters | `chk_<kind>.svh.tmpl` / scoreboard route | yes, small |
| **F5 Assertion cover** | One `a_<name>` assertion | Paired `c_<name>` and activation cover | `assertions.sv.tmpl` | no |
| **F6 Covergroup** | One covergroup row (covergroup, coverpoints, bins) | Map each coverpoint to a monitor field | `plan_coverage.svh.tmpl` | only for field mapping |
| **F7 Tests** | All decided sequences and checks | One test per feature group plus a regression list | `test.svh.tmpl` | no |

A failed required item becomes a recorded question and blocks its dependent stages. Publish no complete functional milestone until its mandatory sequence, checks and monitor-fed coverage are present. Infrastructure-only bring-up has a separate status and does not invent functional comparisons.

## 5. The step contract (applies to every step)

```text
inputs   : one item + fixed option list + ≤2 cited quotes      (≤ 4 KB, hash = cache key)
decide   : deterministic rule → else model (enum/typed fields only) → else question
validate : schema + rules in code (ports exist, widths fit, ids valid, values documented)
record   : decisions/<step>/<item>.json  {decision, source: rule|model|human, citations, status}
render   : template(decision) → files under the project; library files copied
checkpoint: same input hash ⇒ reuse; changed input ⇒ redo only this item
```

Rules that apply everywhere: identifiers are normalized in code; at most two attempts; a refusal returns the
rule and the refused answer; a human answer is final; no step reads another step's prose.

## 6. Customisation

Order of precedence: **owner override > recorded human decision > rule > model**.

- **Overrides file** (`codegen_overrides.json` beside the plan): pin a UVC per interface, bind roles, set
  agent mode, change clock period or reset cycles, disable or replace any item, add parameters. Applied
  before any model call.
- **Library extension.** Drop a folder into `uvc/` with its `uvc.json`. It appears in the catalog for B2
  without code changes. Project-only UVCs can live in a project `uvc/` folder that is searched first.
- **User code is never regenerated.** Generated classes are not edited. A project `user/` folder holds
  subclasses registered with UVM factory overrides, plus `user_tests/`; generation includes them if present
  and never writes there.
- **Template sets are swappable** (`--template-set`), so a team can keep its own coding style.

## 7. Scalability

- **Payload is constant per item**, so a 200-register design costs more steps, not bigger prompts.
- **Items have separate checkpoints** within a step. Execute required stages sequentially; parallel scheduling is future work, not part of initial bring-up.
- **Partial results remain reviewable.** Preserve generated scaffolds and three unresolved questions, but report BLOCKED for an incomplete required milestone. Compilation and execution remain NOT_RUN until actual tool evidence exists.

## 8. What changes, in phases

| Phase | Scope | Done when |
|---|---|---|
| **1. Bring-up** | B0–B5; `gpio` and `passive_monitor` UVCs; `uvc.json` manifests; decision records; overrides file | UART: compiles and passes the bring-up test with zero model calls except B2/B3 leftovers; a second, different design does the same |
| **2. Deterministic features** | F1 register model, F5 assertion covers, F6 covergroups from structured plan fields, F7 tests | Generated from plan data alone; covergroups match the plan table |
| **3. Per-item decisions** | F2, F3, F4 with catalogs and the step contract | Each item ≤ 4 KB input, ≤ 2 attempts; a failing item preserves earlier checkpoints and blocks only its required downstream stages |
| **4. Retire the old stages** | Grouping, dependencies, pseudocode, collation, integration and review become optional reports, not gates | `/code` uses only the new steps; old stages are opt-in |

Phase 1 changes little existing code: the library and templates already cover clock, reset, Wishbone and
serial. Most of the work is the two new library UVCs, the manifests, and moving decisions into records.

## 9. Defaults and acceptance gates

- Undocumented input ownership is a required question, not an automatic passive-driver fallback.
- Keep dependency/pseudocode reports as optional views of structured decisions; they cannot be repeated sources of truth or a second global implementation contract.
- Normal checks use documented or explicit human-approved expectations. Isolated quick-testing inferences keep their test-only label.
- `/code` renders and validates; `/run` explicitly compiles/runs basic bring-up, `/regress` runs the full selected campaign. Do not launch the simulator inside normal generation.
- Register reset reads require documented address, access, mode/bank selection and reset comparison mask. Clear-on-read, FIFO and unsupported side effects are not assumed to be simple storage.

## 9a. Template readiness before enabling a stage

| Component | Existing implementation | Remaining work before deterministic bring-up |
|---|---|---|
| Clock/reset/common environment | Fixed source in `uvc/`, copied unchanged | Validate packaging and copy hashes; configure bindings only |
| Top/package/test/interface composition | Existing `templates/codegen/*.tmpl` | Typed per-stage input contracts and placeholder validation |
| Wishbone/serial agent plumbing | Existing protocol templates | Catalog manifests, documented role binding and config overrides |
| GPIO/passive monitor | Proposed catalog entries | Implement/review library components; do not advertise them as available yet |
| Register reset/read checks | Existing limited register mirror/check templates | Enforce safe-read eligibility per register before enabling |
| Feature sequence/check/coverage | Existing templates and bounded extension hooks | Smaller decision contracts and explicit dependency links |

Before a phase is marked done, inventory every emitted file as copied library,
rendered template or owner extension. Test the reusable library and template
catalog once; per-design changes should be names, ports, widths and configuration.
The model chooses typed parameters; it does not rewrite these library classes.

## 9b. Contained rollout and proof of completion

1. **Library boundary (current):** finish the move out of `templates/`; verify installed package data and byte-for-byte output copies. No DUT behavior changes.
2. **Common-only bring-up:** a separate small BringupPlan (not the full functional CodePlan) binds clock/reset, resets once, idles for a bounded cycle count and records observed edges/reset. No protocol, register model, scoreboard or functional coverage required for this infrastructure milestone.
3. **One interface:** select one catalog UVC, bind roles, configure idle/ownership and connect its monitor. Gate on widths/directions/ownership. Only add protocol transactions after that interface's prerequisites pass.
4. **One safe transaction:** one source-supported register read/write category, then its check and monitor-fed coverage. Explicitly handle side effects and modes. Missing required evidence blocks this item, rather than expanding the prompt.
5. **One feature:** retrieve one stable item, choose a sequence/check/coverage template, validate, render and checkpoint. A separate dependency pass adds shared configuration/sequence-extension or p_sequencer controls as needed.
6. **Compose:** consume the validated decisions, connect components deterministically and publish tests/traceability. `/run` and `/regress` produce execution evidence later.

For each step: fixed input -> bounded decision -> schema/rule validation -> record ->
render -> checkpoint. Cache keys contain only the relevant source, interface,
configuration and library/template hashes. Existing human/quick-test decisions are
read directly, never retrieved as fresh prose and never asked again.

Customization order: explicit owner settings with recorded provenance, existing
reviewed decision, deterministic rule, bounded model choice. Project `user/` sources
and factory overrides are preserved; config manifests describe supported knobs.
No new customization knob is advertised until its parser and rendering path exist.

## 10. Risks

- Catalogs will not cover every protocol; `custom` stays the escape hatch and becomes a question, not a guess.
- Name-alias matching can bind the wrong port if aliases are too loose; aliases are exact or normalized only,
  and every binding is listed in the review report.
- Moving decisions out of plan prose changes where approvals live; existing approvals are migrated once.
