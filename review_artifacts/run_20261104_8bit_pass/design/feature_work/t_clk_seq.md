# Fixed-period clock stimulus

Work package: `t_clk_seq` · stimulus · NEEDS_REVIEW

## Dependent features

- None identified.

## Independent features

None identified.

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Fixed-period clock stimulus drives RTL wb_clk_i spec CLK with one symbolic period P_fixed per test started before reset and held through traffic with observed-edge sampling for band boundary stratum once documented WISHBONE points bands defined

## Preconditions

1. RTL wb_clk_i bound to spec CLK available to drive with fixed period P_fixed per test [f_clk_1]
2. RTL wb_rst_i bound to spec WB_RST_I available to assert before configuration [f_rst_1]
3. Symbolic period P_fixed selected before reset; no value invented where documented bands unresolved
4. Other DUT inputs held idle by respective owners; reset polarity unresolved pending question

## Stimulus pseudocode

```text
1. SELECT symbolic P_fixed for this test; IF documented bands undefined THEN keep P_fixed symbolic without inventing bounds
2. START continuous tone on wb_clk_i with period P_fixed before reset assertion [f_clk_1]
3. ASSERT reset via wb_rst_i; WAIT reset duration scaled to P_fixed; DEASSERT reset before any configuration [f_rst_1]
4. HOLD P_fixed constant through traffic; FORBID period change and jitter injection during operation
5. IF different period required THEN change only between tests before reset and traffic
6. CLEANUP hold clock stable to end of test
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. SAMPLE observed wb_clk_i edges via passive monitor and MEASURE sampled period [f_clk_1]
2. RECORD symbolic sampled band and boundary flag at documented point plus seed stratum low mid high once bands defined; FORBID inventing bounds or sampling gaps
3. FOR each test COVER one sampled band boundary stratum combination; state finite sample does not claim exhaustive coverage
```

## Completion

1. Clock started before reset with period P_fixed and held fixed through traffic
2. Reset asserted via wb_rst_i and deasserted before configuration with duration scaled to P_fixed
3. Observed-edge sampling recorded for this test sampled point where bands defined
4. Terminate on traffic done or TEST_TIMEOUT_CYCLES operational limit; timeout is testbench limit not DUT timing

## Questions

1. What are documented CLK period bands and Max Min Resolution meanings for 3.6864 for 115200 bps and 1258Mhz for 1200 bps points?
2. What is nominal CLK frequency and period to use as P_fixed?
3. What are minimum and maximum operating CLK frequencies periods plus duty-cycle and jitter tolerance?
4. Is dynamic period change during operation permitted or must period stay fixed per test changed only between tests before reset and traffic?
5. What is active level polarity of wb_rst_i and required reset duration in CLK cycles for scaling to P_fixed?

## Essential blockers


## Specification evidence

- `f_clk_1` → `/sections/4/strategy/agents/1` / `CH-63ad4d61a5`
> CLK 1 Input Block’s clock input

- `f_rst_1` → `/sections/4/strategy/agents/1` / `CH-63ad4d61a5`
> WB_RST_I 1 Input Asynchronous Reset

- `f_reset_clear_1` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The receiver and transmitter FIFOs are cleared.

- `f_baud_1` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> (Input Clock Speed)/(Divisor Latch value) = 16 x the communication
> baud rate.
