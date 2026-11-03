# Silicon Copilot (dv_agent) — 3-minute demo video script (v3, reviewed against saved runs)

Speaker: Sreenath. Total: ~180 seconds (~390 spoken words at ~145 wpm, leaving room for footage).
Pre-generate everything; record saved outputs, not live runs.

## 0:00–0:20 — Hook

**VO:** "Hi, I'm Sreenath. Every chip ships with a verification plan and a testbench that prove it does
what its specification promises. Engineers build them by hand, over weeks. Silicon Copilot is an agent
that drafts both from the spec, with every statement traced back to the line it came from."

**On screen:** Title card → the UART16550 spec → the finished test-plan HTML report.

## 0:20–0:45 — One sentence selects the build

**VO:** "I ask in one line: verification collateral for the 8-bit UART. The macro comes from the RTL
itself, so the plan covers only that build. Registers and ports it doesn't have are listed as left out.
Muse Spark then reads the spec and builds the interface groups and register map, each with its
citation. A script checks that every quote is verbatim."

**On screen:** The request and the ask card showing `DATA_BUS_WIDTH_8` → the plan's "Build
configuration" block → interface and register tables with their source tooltips.

## 0:45–1:05 — Refuse and repair

**VO:** "Here's what I'm proudest of. Muse Spark does the reasoning, but scripts it can't override have
the last word. Here it cited a quote that isn't in the retrieved source. It was refused, told why, and
it repaired the answer. Here it ran a test before its dependency. Refused again."

**On screen:** `code_trace.jsonl` lines: `code_pseudocode:t_serial_seq — Fact quote must occur in a
retrieved source excerpt`, then `code_integration — Test test_lsr_errors starts t_lsr_dr_cov before
dependency t_modem_seq`.

## 1:05–1:25 — The plan and its lineage

**VO:** "The result is a thirteen-section plan: strategy, stimulus, checks, coverage. Entries are tagged
as documented, inferred or assumed, and RTL observations are marked for engineer review. One command
walks a section back to its exact spec pages. Thirty-two Muse Spark calls, every section passed."

**On screen:** HTML report scroll; a source tooltip; `dv-agent lineage` on a `TPS-` node showing chunk
and pages; the token table.

## 1:25–1:50 — It writes the testbench

**VO:** "Then it writes the testbench, one unit at a time, smallest interface first, saving each so a run
resumes where it stopped. Four interfaces and twenty-one features became forty-nine sequences and
thirty-seven checks, rendered through fixed templates. Four features it couldn't support are deferred
with reasons, not faked."

**On screen:** `/code` dashboard; the closing summary lines (Status, Features, Built, Open, Set aside);
one generated monitor or sequence.

## 1:50–2:20 — It runs

**VO:** "And it runs, on the real RTL, under Xezim and UVM. This first test is chosen by script: the
model's setup writes, one byte out, one byte in. Two scoreboard comparisons, thirty-seven of
thirty-seven assertions, zero errors. Here's the waveform: 5A written on the bus leaves on the serial
line, and A5 sent in comes back. The file even arrives on Telegram."

**On screen:** `/run wave` output: `quick_basic: PASS`, coverage line, waveform path, `waveform sent to
Telegram` → GTKWave with `wb_dat_i`, `stx_pad_o`, `srx_pad_i`, `wb_dat_o` → the Telegram message.

## 2:20–2:42 — What it does not claim

**VO:** "It's a prototype, and it says so. Five model-designed tests and nine routes are set aside
because they don't pass yet. Hundreds of questions wait for a designer, and approvals here are
test-only. Nothing is signed off. An engineer stays in charge."

**On screen:** The summary's Open and Set aside lines; `Review status: NEEDS_REVIEW`; the `QUICK TESTING
ONLY` banner; `quick_basic_set_aside.json`.

## 2:42–3:00 — Close

**VO:** "Silicon Copilot: from one sentence and a spec to a traceable plan and a running testbench,
honest about what it knows and what it doesn't. Repo link below. Thanks for watching."

**On screen:** Title card with repo URL and: 13 of 13 sections, 32 plan model calls, `quick_basic` PASS,
2 comparisons, 37 of 37 assertions.

---

## Recording notes (not spoken)

- **Source of every figure:** the 2026-11-01 8-bit plan `runs/orch-20261101T140654Z` and its quick-testing
  copy `…-quick-testing-2026-11-01T1423204743620000` (code project `3ab3bda06154454c`).
  Plan: 13 of 13 sections, 32 requests, 20 registers, 7 interface groups. Build: 4 agents, 21 features
  built, 4 deferred, 84 items deferred, 49 sequences (4 of them the script-chosen test's), 37 checks,
  25 plan coverage groups, 399 questions. Run: 2 comparisons, 37 of 37 assertions, 0 UVM errors.
- **Capture the terminal again:** restart the orchestrator, send the 8-bit request and run `/code`, then
  `/run wave`, to film the summary lines and the Telegram line. Saved answers make this about a minute.
  Update the figures above if a new run changes them.
- **Do not use:** `runs/orch-20261103T050924Z`, whose plan timed out and is BLOCKED; build `0f231192…`,
  which came from the hand-written test contract, so it is not what the agent designed; `runs/uart16550`,
  which has BLOCKED sections.
- **Removed from v2, with the reason:**
  - The `--llm off` side-by-side: no such plan is saved.
  - The `review` command and "rejection notes feed back": the CLI has `review-feedback` only, and it was
    not exercised for this film.
  - The claims-check line: it comes from an older run with BLOCKED sections. Basic-mode plans call the
    separate judge for RTL observations only.
  - "Green, yellow, red": the colours were not confirmed in the current report.
  - Coverage 65/65: from a different mode (`uart_fast`), and the filmed runs have no such figure.
- Do not call this RAG or lead with retrieval. The rules list basic RAG apps as an anti-project.
- Do not quote the 58.5% coverage average as a result. It is a plain mean from one test.
- Confirm the UART16550 licence before showing spec pages, and record its source and revision.
- The Langfuse waterfall has no keys configured; use lineage instead.
