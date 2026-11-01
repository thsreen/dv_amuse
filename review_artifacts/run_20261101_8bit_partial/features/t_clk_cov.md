# Clock period coverage

Work package: `t_clk_cov` · coverage · NEEDS_REVIEW

## Dependent features

- `t_bringup_clk`: Clock period-frequency band stratum coverage requires fixed-period clock generation per test.

## Independent features

`t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_uart_cfg`, `t_wb_acc_cov`, `t_wb_mon`, `t_wb_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

t_clk_cov is coverage-only sampling of observed CLK period on wb_clk_i with per-instance false requiring fixed period per test from t_bringup_clk. DOCUMENTED evidence confirms CLK input role and WISHBONE clock table points with SoC deferral. Band stratum boundary min-max resolution and directed nominal-min-max plus random low-middle-high settings remain INFERRED quick-test navigation only and prove only finite sample.

## Preconditions

1. Clock stable at symbolic fixed SYM_PERIOD before reset and traffic with no dynamic change pending
2. Reset assert then deassert coordination complete with wishbone_bus and serial_data and modem_control_if idle
3. wb_clk_i driven by clock with all DUT inputs owned or tied and period change allowed only between tests before reset

## Stimulus pseudocode

```text
1. SET clock to SYM_PERIOD for this test before reset and HOLD fixed through reset and traffic
2. EXECUTE reset assert then deassert then WAIT SYM_IDLE_CYCLES clock cycles for idle
3. HOLD wishbone_bus and serial_data and modem_control_if idle while clock edges accumulate for sampling
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. SAMPLE observed clock edges from clock monitor analysis port on each observed edge of wb_clk_i with per-instance false
2. SAMPLE SYM_OBSERVED_PERIOD into symbolic point bins tracing documented Clocks table points
3. SAMPLE stratum and boundary into symbolic low_stratum middle_stratum high_stratum and nominal min max boundary
4. IF observed period falls in unlisted gap THEN EXCLUDE as never-sampled ignore without DUT failure
5. FOR each test RECORD single fixed SYM_PERIOD and prove only finite sample exercised not exhaustive frequency proof
```

## Completion

1. WAIT until SYM_MIN_EDGES observed clock edges sampled and coverage recorded
2. ENFORCE testbench operational timeout TEST_TIMEOUT_CYCLES as limit not as DUT timing requirement
3. CLEANUP return wishbone_bus and serial_data and modem_control_if to idle and release coordination handles

## Questions

1. What are units nominal min max and resolution for documented WISHBONE clock points 3.6864 for 115200 bps and 1258Mhz for 1200 bps?
2. Confirm clock bands and strata for sampling low-middle-high and nominal-min-max boundaries?
3. What is required sampling edge sample count and per-instance scope for CLK period coverage?
4. How must reset duration and all sequence timing scale with the selected clock period in cycles versus absolute time?
5. Is dynamic clock period change permitted during reset or traffic or must period remain fixed per test?
6. What is active level and assert deassert sequencing for reset coordinated with stable clock before traffic?

## Essential blockers


## Specification evidence

- `f_clk_input` → `/interfaces/groups/1` / `CH-63ad4d61a5`
> CLK 1 Input Block’s clock input

- `f_clk_wb` → `/sections/10/entries/8` / `CH-8e56094e71`
> WISHBONE
> clock

- `f_point_1200` → `/sections/10/entries/8` / `CH-8e56094e71`
> 1258Mhz for
> 1200 bps

- `f_point_115200` → `/sections/10/entries/8` / `CH-8e56094e71`
> 3.6864 for
> 115200 bps
