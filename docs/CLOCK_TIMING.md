# Clock timing in planning and generated tests

The verification strategy records the clock's nominal frequency/period, documented
operating bands, randomization approach, change policy and unresolved questions in
`strategy.clock_timing`. The overview stays high level. The Verification Plan has a
**Clock Timing and Randomization** subsection covering sequence configuration,
boundaries, seeds, reset duration and monitor-based timing coverage. Both sections
retain source citations and inference status. Clock timing is explicitly retrieved
when generating strategy, implementation plan, stimulus and coverage.

A clock review can resolve the port, nominal `clock_period_ns` (including fractional
nanoseconds), or `clock_period_ranges`. The dedicated approval revision now updates
both strategy and verification plan as well as the audit addendum. Human decisions
remain attributed to the human; quick-testing decisions stay inferred and test-only.
A nominal testbench period alone does not establish the DUT's legal operating range.
Previously generated reports are not rewritten silently; regenerate `/plan` for the
new planning prompts, or apply a new clock review through the normal revision flow.

## Executable clock policy

`ClockUnit` and `CodePlan` carry numeric bands, for example:

```json
{
  "clock_period_ranges": [
    {
      "name": "operating",
      "min_ps": 2500,
      "max_ps": 5000,
      "nominal_ps": 3500,
      "cited_chunk_ids": ["CH-clock"],
      "provenance": "DOCUMENTED",
      "inference_reason": ""
    }
  ]
}
```

These example limits are usable only if the cited source actually supports them.
Each endpoint and nominal needs numeric evidence with units or reviewed ps fields.
A band must be explicitly paired in that evidence: separate operating bands cannot
be merged across a gap. Unrecognized source formatting needs clarification rather
than an invented envelope. Normal generation refuses inferred operating ranges;
quick-testing mode permits its explicitly recorded test-only decisions.

Periods use integer picoseconds, currently 2 ps through 1,000,000,000 ps (1 ms).
Sub-resolution or out-of-capability settings are rejected. Frequency conversion is
`period_ps = 1,000,000 / frequency_MHz`; maximum frequency gives minimum period.
Round a lower period bound up and an upper bound down at 1 ps resolution to stay
inside the stated band. Do not assume an unsupported frequency tolerance.

For **every** functional test and **every** band, the manifest schedules:

- Minimum and maximum period.
- Documented nominal period, or an explicitly named midpoint sample if none exists.
- One seeded random draw from each of three equal period-space strata (fewer strata
  only when fewer than three integer-ps choices exist).

This is reproducible from the test seed. Every draw stays in its own band; gaps are
never sampled. This is uniform sampling in period-space, not frequency-space, and
finite sampling is not a claim of exhaustive value coverage. `/run` executes the
first basic directed case; `/regress` executes the complete generated campaign.

## Simulation and observed evidence

Each case passes `+CLOCK_PERIOD_PS` to the original UVM test class. Its period is
selected **before reset** and held fixed through traffic. There is no implicit
cycle-to-cycle jitter or live frequency switching. Those require a separate source-
supported strategy. Reset duration follows the selected period and cycle count.

The reusable clock/reset timing fields preserve fractional nanoseconds. The clock
driver splits odd-ps periods into quantized high/low intervals whose sum is exact;
both intervals must be at least 1 ps. Clock monitor timestamps use `$realtime`.

Clock coverage subscribes to monitor rising-edge observations. It samples complete
periods into per-band boundary/nominal/stratum bins, reports the measured period and
checks it against the selected source setting. This is clock-source infrastructure
health, not a DUT functional scoreboard. Runtime reports retain the selected case
and observed periods. Missing monitor evidence blocks a campaign case; disagreement
fails it. Planning metadata stays `NOT_RUN` until there is actual simulation evidence.

If no approved bands exist, the nominal clock remains available for bring-up, but
the manifest says `NOT_CONFIGURED` and the code questions explicitly request the
missing bounds. The generator does not silently randomize around its legacy default.
The current code contract has one generated source clock; multi-clock relationships
remain planning concerns unless supported by a separately extended contract.
