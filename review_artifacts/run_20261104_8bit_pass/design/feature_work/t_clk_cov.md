# Clock period coverage

Work package: `t_clk_cov` · coverage · NEEDS_REVIEW

## Dependent features

- `t_clk_seq`: period band boundary stratum coverage needs fixed-period clock stimulus

## Independent features

`t_addr_dlab_cov`, `t_chip_reset`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_init_cfg`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Clock period coverage samples observed wb_clk_i spec CLK edges with one symbolic fixed period P_fixed per test started before reset and held through traffic; raw period sampling is supported, band boundary stratum classification deferred until documented bands defined with no invented bounds or dynamic switching.

## Preconditions

1. DUT clock input wb_clk_i spec CLK available f_clk_1
2. DUT reset input wb_rst_i spec WB_RST_I available as asynchronous reset f_reset_1
3. Symbolic fixed period P_fixed selected per test as testbench infrastructure choice started before reset and held fixed through traffic
4. No DOCUMENTED band boundary or stratum limits assumed

## Stimulus pseudocode

```text
1. START clock on wb_clk_i with symbolic period P_fixed before reset
2. ASSERT reset via wb_rst_i at symbolic active level R_ACTIVE then DEASSERT before traffic with duration scaled to P_fixed by symbolic count N_RST
3. HOLD clock period at P_fixed through traffic with no dynamic change or jitter injection
4. WAIT for traffic activity to provide sampleable clock edges
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. SAMPLE observed clock edges on wb_clk_i and MEASURE sampled period P_sampled per observation window
2. SAMPLE raw period P_sampled with P_fixed and test seed without inventing band boundary or stratum
3. IF documented band map with boundary and low middle high strata becomes available THEN COMPARE P_sampled to that map ELSE retain P_sampled raw for later classification
4. SAMPLE per-test fixed-period context without claiming exhaustive coverage
```

## Completion

1. WAIT for traffic done OR TEST_TIMEOUT_CYCLES operational limit; timeout is testbench operational limit not DUT timing
2. STOP sampling and retain P_fixed with P_sampled and test seed for this test then CLEANUP to idle without mid-test period change

## Questions

1. What are documented CLK period bands and Max Min Resolution meanings for 1258Mhz for 1200 bps and 3.6864 for 115200 bps points?
2. What is nominal CLK frequency and period to use as P_fixed?
3. What are minimum and maximum operating CLK frequencies periods plus duty-cycle and jitter tolerance?
4. Is dynamic period change during operation permitted or must period stay fixed per test changed only between tests before reset and traffic?
5. What is active level polarity of wb_rst_i and required reset duration in CLK cycles for scaling to P_fixed?

## Essential blockers


## Specification evidence

- `f_clk_1` → `/sections/4/strategy/agents/1` / `CH-63ad4d61a5`
> CLK 1 Input Block’s clock input

- `f_reset_1` → `/sections/4/strategy/agents/1` / `CH-63ad4d61a5`
> WB_RST_I 1 Input Asynchronous Reset
