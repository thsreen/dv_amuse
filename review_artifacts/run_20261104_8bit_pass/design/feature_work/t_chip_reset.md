# Chip reset bring-up sequence

Work package: `t_chip_reset` · verification_plan · NEEDS_REVIEW

## Dependent features

- `t_clk_seq`: reset_drive coordination needs stable fixed-period clock_generate defined first

## Independent features

`t_clk_cov`, `t_irq_baud_mon`, `t_irq_id_cov`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Chip reset bring-up starts stable fixed-period clock on wb_clk_i before asserting asynchronous reset on wb_rst_i as first step before any configuration, tracking duration to symbolic P_fixed; quick-test-only active-high 10-cycle hold is testbench choice not documented DUT requirement.

## Preconditions

1. Symbolic period P_fixed selected for this test and held fixed with no dynamic switching during reset
2. Physical bindings CLK to wb_clk_i and WB_RST_I to wb_rst_i available for drive and monitor
3. No register configuration or traffic started; wishbone_slave_interface uart_serial_data modem_control_if hold DUT inputs idle and interrupt_output only observed during reset
4. Monitors sample wb_rst_i and wb_clk_i edges for reset duration tracking to P_fixed

## Stimulus pseudocode

```text
1. START clock on wb_clk_i with period P_fixed before reset and HOLD fixed through reset
2. WAIT for stable clock edges for testbench stabilization limit
3. ASSERT reset on wb_rst_i to quick-test-only active level for quick-test-only hold of 10 clock cycles scaled to P_fixed; levels and cycles are testbench choice not documented DUT timing
4. SAMPLE reset assertion and clock edges on monitors to track reset duration to P_fixed
5. DEASSERT reset on wb_rst_i to complementary inactive level
6. WAIT for post-reset stabilization on clock edges before any configuration then CLEANUP to configuration stage
7. IF reset not completed within TEST_TIMEOUT_CYCLES operational limit THEN abort bring-up; timeout is testbench limit not DUT timing
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
```

## Completion

1. Reset asserted then deasserted on wb_rst_i before any register configuration with duration tracked to symbolic P_fixed
2. Clock on wb_clk_i started before reset with period P_fixed and held fixed through reset
3. Terminate on reset done or TEST_TIMEOUT_CYCLES operational limit; timeout is testbench limit not DUT timing

## Questions

1. What is documented active level polarity and inactive level of WB_RST_I on wb_rst_i? Excerpt states only Asynchronous Reset with no polarity.
2. What is documented minimum assert duration in clock cycles for WB_RST_I and required deassert to configuration delay before init_config_sequence?
3. What is documented nominal CLK period P_fixed and permitted operating range when clocks excerpt lists only labels 3.6864 for 115200 bps and 1258Mhz for 1200 bps with Max Min Resolution unresolved?

## Essential blockers


## Specification evidence

- `f_reset_async` → `/interfaces/groups/2/property_evidence/function` / `CH-63ad4d61a5`
> WB_RST_I 1 Input Asynchronous Reset

- `f_clk_input` → `/sections/4/strategy/agents/1` / `CH-63ad4d61a5`
> CLK 1 Input Block’s clock input

- `f_fifo_clear` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The receiver and transmitter FIFOs are cleared.

- `f_shift_clear` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The receiver and transmitter shift registers are cleared

- `f_div_zero` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The Divisor Latch register is set to 0.

- `f_lcr_default` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The Line Control Register is set to communication of 8 bits of data, no parity, 1

- `f_ier_disable` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> All interrupts are disabled in the Interrupt Enable Register.
