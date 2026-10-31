# Silicon Copilot (dv_agent) — 3-minute demo video script

Speaker: Sreenath. Total: ~180 seconds (~435 spoken words at ~145 wpm).
Cut to a timer in editing; each beat lists voiceover (VO) plus what is on screen.

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

## 0:45–1:05 — Refuse and repair (20s, ~50 words)

**VO:** "Here's the part I'm proudest of. The model once proposed a signal that doesn't exist in the
spec. The checker refused the whole section, handed the failure back with reasons, and the model
repaired it — citing real evidence this time. The model never approves its own work."

**On screen:** Trace/log excerpt showing `refusal:interfaces` → repair → PASS; before/after entries.

## 1:05–1:25 — Strategy (20s, ~50 words)

**VO:** "Next the agent proposes the verification strategy: which UVM agent drives and monitors each
interface, what each scoreboard compares, and how every check proves its behavior. A clock source gets
no scoreboard — there's nothing to compare — while buses get the full treatment. Architecture choices
stay visibly marked as engineering proposals, never spec claims."

**On screen:** Strategy section bullets with per-point provenance badges; scoreboard inputs diagram.

## 1:25–1:50 — Configurations and the claims check (25s, ~60 words)

**VO:** "Configurations randomize only values the spec actually states. And when two spec sections
disagree about a register, the plan doesn't guess — it raises a designer question. Then a separate
claims-check call judges every documented entry against its own quotes. One over-broad claim gets
downgraded to an assumption rather than shipped as fact."

**On screen:** Configurations table; register-conflict designer question; claims-check verdict excerpt.

## 1:50–2:20 — The plan and its lineage (30s, ~70 words)

**VO:** "The result is a complete, thirteen-section test plan: stimulus, checks, coverage, all cross
linked. Green means documented, yellow means inferred, red means no verified reference — and each
badge links to the source appendix. Pick any entry and Langfuse traces it back through reranking,
retrieval, and extraction to the exact spec line. If the evidence isn't there, the plan says so."

**On screen:** Full HTML report scroll; click a badge → appendix excerpt; Langfuse trace waterfall.

## 2:20–2:45 — Human sign-off, and why the model matters (25s, ~55 words)

**VO:** "Finally, a verification engineer signs off — rejection notes feed back into revision. And to
prove the model does load-bearing work, here's the same run with the model disabled: structure, but
no requirements, no strategy, no judgment. The semantic work is all Muse Spark; the honesty is all
deterministic checks."

**On screen:** Sign-off command; side-by-side `--llm off` vs `--llm on` plans.

## 2:45–3:00 — Close (15s, ~35 words)

**VO:** "Silicon Copilot: from specification to a traceable, reviewable verification plan — honest
about what it knows and what it doesn't. Repo link below. Thanks for watching."

**On screen:** Title card with repo URL and run stats (34 API calls, 13 of 13 sections PASS).

---

## Recording notes (not spoken)

- Pre-generate the plan; record the dashboard replay plus the saved HTML/Langfuse, not a live 20-minute run.
- Blur or confirm the spec license before showing pages (UART16550; record source and revision).
- Keep the `--llm off` contrast to one split-screen shot; it exists to answer the tooling question.
