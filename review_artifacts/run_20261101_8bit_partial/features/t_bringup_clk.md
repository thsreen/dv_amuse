# Bring-up clock and reset

Work package: `t_bringup_clk` · bringup · NEEDS_REVIEW

## Dependent features

- None identified.

## Independent features

`t_modem_seq`, `t_serial_seq`, `t_wb_seq`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Bring-up requires fixed-period clock per test with reset assert then deassert coordinated across bus serial and modem interfaces. Documented evidence confirms reset-cleared FIFOs known outputs after reset and WISHBONE clock table points but leaves period strata units polarity duration scaling and idle-check values unresolved so plan retains symbolic coordination only with no DUT timing claims.

## Preconditions

1. Clock on wb_clk_i and reset on wb_rst_i connected and owned by common clock and reset controls
2. Single symbolic PERIOD_TEST selected before reset and held fixed during reset and traffic
3. No wishbone_bus serial_data or modem_control_if traffic active before power_on_reset coordination completes

## Stimulus pseudocode

```text
1. CONFIGURE the clock to symbolic PERIOD_TEST before any reset or traffic and do not change period during reset or traffic
2. WAIT for the clock stable for SYM_STABLE_CYCLES clock cycles
3. ASSERT the reset to symbolic active level SYM_RESET_ACTIVE and HOLD for SYM_RESET_CYCLES scaled to PERIOD_TEST
4. DEASSERT the reset to symbolic inactive level and WAIT SYM_SETTLE_CYCLES clock cycles for settling
5. SPAWN per-interface idle handling on wishbone_bus serial_data and modem_control_if via explicit sequencer handles from power_on_reset coordination with spawn only and no delays and no virtual-interface access
6. FOR each directed documented point and each seeded random stratum sample in separate test REPEAT bring-up with PERIOD_TEST fixed per test
7. IF period change is required APPLY change only between tests before reset and traffic never during reset or traffic
```

## Check pseudocode

```text
1. COMPARE DUT outputs for known non-X or non-Z values after wb_rst_i deassertion
2. COMPARE receiver and transmitter FIFOs for cleared empty state after reset before further traffic
```

## Coverage pseudocode

```text
1. SAMPLE observed clock edges via clock monitor analysis port to classify PERIOD_TEST into symbolic band and stratum bins
2. SAMPLE boundary classification for documented points without claiming exhaustive frequency proof or gap coverage
```

## Completion

1. WAIT for reset deassertion plus SYM_IDLE_CYCLES clock cycles then declare bring-up complete
2. ENFORCE testbench operational timeout TEST_TIMEOUT_CYCLES as limit not as DUT timing requirement
3. CLEANUP return wishbone_bus serial_data and modem_control_if to idle and release coordination handles

## Questions

1. What is the active level and polarity of wb_rst_i and required assert and deassert sequencing?
2. What are units nominal min max and resolution for documented WISHBONE clock points 3.6864 for 115200 bps and 1258Mhz for 1200 bps?
3. How must reset duration and all sequence timing scale with the selected clock period in cycles versus absolute time?
4. What idle register and pin check is required after deassertion before configuration and what values indicate success?
5. Is dynamic clock period change permitted during reset or traffic or must period remain fixed per test?

## Essential blockers


## Specification evidence

- `f_fifo_cleared` → `/sections/5/entries/9` / `CH-1e2324cfc3`
> The receiver and transmitter FIFOs are cleared.

- `f_outputs_known` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> Upon reset the core performs the following tasks:

- `f_clk_115200` → `/sections/10/entries/8` / `CH-8e56094e71`
> 3.6864 for
> 115200 bps

- `f_clk_1200` → `/sections/10/entries/8` / `CH-8e56094e71`
> 1258Mhz for
> 1200 bps
