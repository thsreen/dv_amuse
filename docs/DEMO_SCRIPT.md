# Silicon Copilot (dv_agent) — 3-minute demo video script (v2, evidence-checked)

Speaker: Sreenath. Total: ~180 seconds (~435 spoken words at ~145 wpm).
Cut to a timer in editing; each beat lists voiceover (VO) plus what is on screen.
Every on-screen claim below is backed by a real artifact named in Recording notes.
Pre-generate everything; record saved outputs, not live runs.

## 0:00–0:20 — Hook: the problem (20s, ~50 words)

**VO:** "Hi, I'm Sreenath. Every chip ships with a verification test plan — hundreds of checks
that prove the design does what its specification promises. Today engineers write those plans by
hand, over weeks, from hundred-page specs. I built Silicon Copilot: an agent that drafts the plan
from the spec, with every statement traced back to the exact line it came from."

**On screen:** Title card → a real spec PDF (UART16550) → a finished test-plan HTML report.

## 0:20–0:45 — Spec in, structure out (25s, ~60 words)

**VO:** "I point it at the spec. Muse Spark reads the prose and tables, and isolates the design's
interface groups and its register map. Notice every signal and every register carries its citation —
document, chunk, page. The deterministic layer then verifies each quote is a verbatim substring of the
source. Nothing the model invents can slip through as fact."

**On screen:** Terminal `/plan` running with the live dashboard; interface groups and register map
rendering with green DOCUMENTED badges and source tooltips.

## 0:45–1:05 — Refuse and repair, for real (20s, ~50 words)

**VO:** "Here's the part I'm proudest of. In this run the model emitted six empty configurations —
fields with no names the checks couldn't resolve. The checker refused the whole section, handed the
failure back with reasons, and the model repaired it. That refusal is saved in the report, and the
model never approves its own work."

**On screen:** Saved report excerpt: `Refused (attempt 1): configuration for '' dropped…` →
`Repaired after 1 refusal(s).` (runs/uart16550/testplan_doc.md, Configurations.)

## 1:05–1:30 — Strategy and the claims check (25s, ~60 words)

**VO:** "Next the agent proposes the verification strategy: which UVM agent drives and monitors each
interface, what each scoreboard compares. Architecture choices stay visibly marked as engineering
proposals, never spec claims. Then a separate claims-check call judges documented entries against
their own cited text — thirteen claims checked against their quotes in this section, all supported."

**On screen:** Strategy bullets with provenance badges; `Claims check: 13 claim(s) judged against
their cited text; all supported.` (runs/uart16550/testplan_doc.md, Feature Description.)

## 1:30–1:52 — The plan and its lineage (22s, ~55 words)

**VO:** "The result is a complete fifteen-section test plan: stimulus, checks, coverage, all cross
linked. Green means documented, yellow means inferred, red means no verified reference — and each
badge links to the source appendix. And any entry traces back with one command, through retrieval
and extraction, to the exact spec line. If the evidence isn't there, the plan says so."

**On screen:** Full HTML report scroll; click a badge → appendix excerpt; `dv-agent lineage`
walking one entry back to its chunk.

## 1:52–2:20 — It runs: code, compile, simulation (28s, ~68 words)

**VO:** "The plan isn't the end. Documented items feed code generation: a UVM testbench with
sequences, scoreboards, and assertions. It compiles clean under Xezim — and then it simulates.
Forty-five hundred assertion passes, zero failures, with functional coverage recorded. Spec to plan
to passing sim, every step traceable."

**On screen:** Terminal: compile PASS → simulation log tail → `assertion_pass_total: 4516,
assertion_fail_total: 0` → coverage excerpt. (codegen-acceptance build 0f231192803d1ef2.)

## 2:20–2:40 — Human sign-off, and why the model matters (20s, ~50 words)

**VO:** "Finally, a verification engineer signs off — rejection notes feed back into revision. And to
prove the model does load-bearing work, here's the same run with the model disabled: structure, but
no requirements, no strategy, no judgment. The semantic work is all Muse Spark; the honesty is all
deterministic checks."

**On screen:** `review` command; side-by-side `--llm off` vs `--llm on` plans.

## 2:40–3:00 — Close (20s, ~40 words)

**VO:** "Silicon Copilot: from specification to a traceable, reviewable verification plan — and a
simulation that proves it. Honest about what it knows and what it doesn't. Repo link below. Thanks
for watching."

**On screen:** Title card with repo URL and run stats (32 model calls, 15 of 15 sections PASS).

---

## Recording notes (not spoken)

- Pre-generate the plan; record the dashboard replay plus the saved HTML and trace excerpts, not a
  live 20-minute run. No live API calls on camera.
- Footage map (all verified 2026-11-02): interface/register badges —
  runs/uart_fast/testplan_doc.html (114 DOCUMENTED badges, 65/65 coverage) or the Nov 1 run's
  dv/testplan_doc.html (15/15 PASS, 20 registers, 7 groups); refusal excerpt —
  runs/uart16550/testplan_doc.md Configurations; claims line — same file, Feature Description;
  token table (32 calls) — Nov 1 run dv/testplan_doc.md; lineage — `dv-agent lineage` on any
  TPS-/REQ- node; sim — codegen-acceptance build 0f231192803d1ef2 simulation/run.json and log.
- Do NOT show: Langfuse waterfall (no keys configured — use lineage instead), the orch runs'
  coverage denominator (empty in basic mode — use uart_fast's 65/65 if coverage is shown),
  anything from `runs/uart16550` beyond the two cited excerpts (it has BLOCKED sections).
- Blur or confirm the spec license before showing pages (UART16550; record source and revision).
- Keep the `--llm off` contrast to one split-screen shot; it exists to answer the tooling question.
- Sync the closing numbers to whatever run is filmed (currently: 32 calls, 15/15 PASS).
