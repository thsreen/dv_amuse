# Specification and RTL port comparison

The coding flow requires independently extracted specification and RTL port inventories before
generating SV interfaces or verification collateral. Order:

1. Load the selected testplan's `interfaces` inventory (extraction status `PASS`).
2. Load the configured RTL `interface_definition.json` inventory.
3. Compare every port's identity, direction relative to the DUT, and resolved bit width.
4. Independently audit the proposed comparison against the original inventories and review decisions.
5. Continue to clock/reset binding, SV interfaces and DV collateral only when **both** results are `PASS`.

This gate runs in orchestrator `/code`, `build-code` (including explicit contracts), and `plan-code`.
It runs before model implementation calls or SV template rendering and is repeated on retries.
The standalone low-level `rtl-agent` extraction/export tools remain independent; they do not
claim specification alignment. The compact RTL interface JSON format is unchanged.

## Design-independent implementation

Comparison, independent validation and relationship context consume supplied inventories; they have
no project-name, register-name, clock-name, data-width or protocol-name branches. Source groups and
their protocol/peer labels are data, including project-defined protocols and bidirectional ports.
Each implementation separately indexes normalized RTL names, retaining ambiguity checks, and group
membership is indexed for reuse. Finite configuration width choices are not limited to two variants.
The independent auditor retains its own matching and width logic.

Synthetic tests exercise stream, memory, sensor and custom interfaces plus a 512-port inventory.
The UART acceptance helper stays under `tests/`, with its explicitly selected source, configuration
and review decisions; it is never imported by production code. Reusable WISHBONE/serial backends are
protocol capabilities in the existing code-generation catalog, not assumptions about the selected
DUT. Other protocols use the existing custom extension path; alignment PASS does not establish that
an arbitrary protocol implementation is available or verified.

## Reports and blocking conditions

The code output directory contains `interface_port_comparison.json` and
`interface_port_comparison.md`. Rows include specification and RTL names, widths, directions,
specification chunk IDs, and mismatch reasons. The functional code manifest includes the comparison.
The orchestrator preview/progress includes **Compare specification ports with RTL ports**.

## Independent validation gate

`codegen/port_validation.py` is a separate deterministic auditor. It does not call the comparison's
matcher, width parser or relationship-context builder, and does not accept a producer's `PASS` as
proof. It independently checks inventory/row completeness, unique one-to-one coverage, source widths
and directions, legal reviewed aliases/configuration choices and snapshot hashes. It checks copied
source metadata, group membership, roles, polarity, quotes and per-property provenance against the
original inventory, including contradictions between group signal properties and the primary spec
inventory. It requires no API call.

The separate **Independently validate specification/RTL comparison** progress step writes
`interface_port_validation.json` and `.md`, with check categories, snapshot/report hashes and failure
reasons. The comparison embeds `independent_validation`, which also reaches the code manifest.
Binding context and common aliases require a passing validation tied to the exact report contents.
Changed or legacy unvalidated reports supply no trusted context; the coding flow regenerates and
audits against its current inputs. Report hashes detect content changes; they are not signatures or
a substitute for authenticated human approval.

This independently validates the *comparison and relationship copying*, using the two independently
extracted inventories. It does not prove that either extractor captured every fact from the original
PDF/RTL, and it does not constitute functional or engineer sign-off. Tests deliberately corrupt
reports and replace the producer's width parser to verify that this independent gate blocks before
SV generation.

## Shared context for later binding

The JSON report also carries `relationship_context`: each spec signal's matched RTL name, match
basis, physical width/direction, drive/observe responsibility, description, original spec quote and
location, documented active level and availability. Interface groups carry protocol, function, DUT
role, connected peer and the original per-property evidence/provenance. RTL references identify the
configured inventory's source files and parameters; compact JSON does not provide declaration line
numbers or internal dependency analysis, and this step does not invent those relationships.

Later grouping, basic interface declarations, infrastructure assessment and binding requests receive
`spec_rtl_relation` scoped to their ports. Feature requests with a known interface use that agent's
ports. Common clock/reset binding reuses the same verified aliases. The report is recomputed against
the current inventories and recorded decisions; a blocked or stale mapping cannot supply trusted
context. Reviewed choices participate in work checkpoint identity to prevent stale reuse.

Retrieval uses both spec and RTL names, prioritizes the relevant source-group items and pins existing
quoted declarations when they can be found in the original source. Existing per-request limits still
apply. Shared quotes are deduplicated in model context, with references retaining their provenance.
Prompts reuse resolved identities and documented properties rather than requesting them again.
Physical direction establishes who drives or observes a wire; it does not establish protocol
semantics. Inferred roles stay inferred, and missing/contradictory required semantics still need review.
This enrichment requires no additional model call.

Missing/extra/duplicate ports, ambiguous matches, direction mismatches, unknown widths and width
mismatches block generation. Source flags explicitly marking width or direction undocumented also
block. Case and separator differences may normalize automatically, only when the match is unique.
Functional aliases are never guessed. A missing specification port cannot be filled from RTL to
make the comparison pass. A genuine discrepancy needs correction of the appropriate input or an
approved specification clarification, followed by a new comparison.

## Reviewed aliases and configuration choices

A reviewer can save `interface_port_mapping.json` beside the reports. Use the **actual** `spec_hash`
and `rtl_hash` values printed in the JSON comparison; changed inventories invalidate the decision.
For example (replace all placeholder values):

```json
{
  "spec_hash": "<from comparison report>",
  "rtl_hash": "<from comparison report>",
  "reviewer": "<reviewing engineer>",
  "reason": "<why these names and this configured variant correspond>",
  "mappings": {"SYS_CLK": "core_clk_i"},
  "width_choices": {"DATA_I": 8},
  "inactive_spec_ports": {"DEBUG_O": "DEBUG_ENABLE is disabled in this configured RTL snapshot"}
}
```

All three decision maps are optional. Aliases must match exactly one RTL port; one RTL port cannot
serve two specification signals. Width choices select from a finite set of explicitly documented numeric
alternatives (`12 or 24 or 48`, `12/24/48`, `12, 24, or 48`, or a JSON integer array),
and must still equal the extracted RTL width. They cannot override
an unconditional specification width. An inactive port must have a documented availability condition
and a review reason; this does not suppress an actual extra RTL port. Other symbolic widths remain
unresolved until source extraction/configuration supplies a concrete supported value.

Rerun `/code` after recording the review or correcting the inputs. Passing aliases are reused by
clock/reset binding against the same inventories. The comparison establishes interface alignment;
it does not approve reset polarity, timing, protocol behavior or functional correctness.

## Automatic reconciliation and review

Recoverable naming/configuration questions now enter the existing `interface_port_alignment`
clarification workflow instead of stopping with a generic error. The request contains source quotes
and locations, all affected signals, compatible unmatched RTL candidates and proposed configuration
choices. A unique direction/width-compatible candidate is a proposal, not proof of functional identity.
Questions distinguish spec logical names from physical RTL connectivity and explain the effect on
the generated interfaces. Normal runs require the human's natural-language decision and explicit
confirmation; timeout follows the existing Hermes/Telegram escalation and remains `WAITING_HUMAN`.

`--quick-testing-auto-approve-inferences` sends the same scoped request to the configured evaluator,
only in its isolated test run. It prints the question/response and retains the existing demo pause.
Accepted decisions remain `TEST_AUTO_APPROVED`, `test_only`, with assumptions and inferred provenance;
they cannot be consumed in normal mode or revise the canonical plan. Invalid/incomplete proposals
remain pending, with validation details in `human_review/*/auto_evaluation.json`.

Before approval, every proposal must pass the comparator **and** independent audit. The dedicated
approval workflow then publishes versioned JSON/Markdown/HTML plan addenda with the human attribution
or test-only inference label, without rewriting original spec facts. It writes the snapshot-bound
mapping file, reloads the revised plan and runs both gates again before generation continues.
Interrupted runs can recover the mapping from the published, validated approval without asking again.
Changed inventories require fresh review; superseded mappings are preserved in `port_mapping_history/`.

Case/whitespace-only differences between a conditional availability phrase and its original quote
can establish direct text support despite an older extraction flag. Producer and auditor check this
independently; missing quote support and directly negated conditions do not pass this fallback. The
original extraction record is preserved. Genuine width/direction mismatches, unsupported symbolic
widths, undocumented required properties, unconditional missing ports and audit defects remain
blocked; the review channel cannot waive them.
