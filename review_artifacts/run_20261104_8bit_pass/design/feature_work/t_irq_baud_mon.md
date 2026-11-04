# Interrupt and baud passive monitors

Work package: `t_irq_baud_mon` · verification_plan · NEEDS_REVIEW

## Dependent features

- `t_clk_seq`: baud period stability observation needs fixed-period clock first

## Independent features

`t_addr_dlab_cov`, `t_chip_reset`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_init_cfg`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Build passive INT_O observation via interrupt_output agent timestamped on fixed-period clock without driving; optional 16x baud-tick observation pending physical binding and documented period mapping; reset clears pending state and restarts measurement.

## Preconditions

1. Clock runs at fixed period P_fixed started before reset and held through observation
2. Reset asserted to active level via wb_rst_i then deasserted to inactive level before observation
3. interrupt_output monitor bound passive to int_o with no drives
4. Optional baud tick binding unresolved; monitors drive no DUT inputs

## Stimulus pseudocode

```text
1. WAIT for reset deasserted to inactive level
2. FOR each wb_clk_i edge SAMPLE int_o via interrupt_output monitor without driving
3. IF int_o edge detected THEN CREATE event with clock timestamp and SEND to analysis port
4. IF reset asserted to active level THEN CLEAR pending events and RESTART timestamp base
5. IF optional baud tick output is bound THEN FOR each wb_clk_i edge SAMPLE tick and MEASURE interval ELSE SKIP tick observation
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. SAMPLE int_o edge toggles and timestamp deltas via dedicated subscriber tapping interrupt_output monitor analysis port
2. IF optional baud tick output is bound THEN SAMPLE observed tick intervals via dedicated subscriber without asserting expected period
```

## Completion

1. End observation after traffic done plus drain_cycles to flush pending interrupt events
2. Abort on request_timeout_cycles operational limit; timeout is testbench limit not DUT timing

## Questions

1. What is documented INT_O polarity and inactive level for assertion versus deassertion observation?
2. Is BAUD_O present on uart_top.v and what is its exact physical port name and UART_HAS_BAUDRATE_OUTPUT enable for binding?
3. What is documented divisor to 16x tick period mapping and which divisor value stalls or disables tick for stability checks?
4. What is active level polarity of wb_rst_i and required reset duration in CLK cycles for clearing pending events?
5. What is nominal P_fixed CLK period to use for INT_O and tick timestamping?

## Essential blockers


## Specification evidence

- `f_core_interrupt` → `/sections/4/strategy/agents/3` / `CH-d62a4ba2db`
> The core requires one interrupt.

- `f_baud_tick` → `/interfaces/groups/6/property_evidence/function` / `CH-8c2c8e9408`
> BAUD_O 1 Output Optional baud rate output signal.
> The signal here is the 16 x actual baud rate.

- `f_clk_input` → `/sections/4/strategy/agents/2` / `CH-63ad4d61a5`
> CLK 1 Input Block’s clock input

- `f_reset_input` → `/sections/4/strategy/agents/2` / `CH-63ad4d61a5`
> WB_RST_I 1 Input Asynchronous Reset
