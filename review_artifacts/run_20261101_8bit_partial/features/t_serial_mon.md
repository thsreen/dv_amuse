# Serial data monitor

Work package: `t_serial_mon` · monitor · NEEDS_REVIEW

## Dependent features

- `t_bringup_clk`: Serial pad sampling requires stable clock and reset order to reconstruct frames.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_uart_cfg`, `t_wb_acc_cov`, `t_wb_mon`, `t_wb_seq`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Passive serial_data monitor observing DUT-output stx_pad_o as tx and DUT-input srx_pad_i as rx for RS232 external-device communication without driving, depending on t_bringup_clk clock and reset order, reconstructing frame transactions for downstream comparison with reset flush.

## Preconditions

1. Bring-up t_bringup_clk complete with stable clock at fixed period per test and reset deasserted with SYM_IDLE_CYCLES idle before sampling
2. serial_data monitor bound observe-only to RTL ports stx_pad_o and srx_pad_i with no driver enabled in monitor and SRX driving owned outside monitor
3. Symbolic SYM_LINE_FORMAT and SYM_BIT_CYCLES configuration references available for sampling without invented values

## Stimulus pseudocode

```text
```

## Check pseudocode

```text
1. SAMPLE stx_pad_o as DUT-output tx and srx_pad_i as DUT-input rx on each clock without driving either pad [f_stx_dir f_srx_dir]
2. IF reset asserted THEN flush partial tx and rx frame state and shift-register state and WAIT for reset deassertion plus SYM_IDLE_CYCLES before resuming SAMPLE
3. FOR each start-bit detected on stx_pad_o RECONSTRUCT one tx frame transaction using symbolic SYM_LINE_FORMAT and SYM_BIT_CYCLES with mid-bit sampling reference and PUBLISH to tx analysis port
4. FOR each start-bit detected on srx_pad_i RECONSTRUCT one rx frame transaction using symbolic SYM_LINE_FORMAT and SYM_BIT_CYCLES with mid-bit sampling reference and PUBLISH to rx analysis port
5. NEVER drive srx_pad_i or stx_pad_o from monitor and NEVER compare tx against itself or rx against itself
```

## Coverage pseudocode

```text
```

## Completion

1. WAIT until all reconstructed tx and rx transactions are published and consumed or TEST_TIMEOUT_CYCLES testbench operational limit expires
2. CLEANUP flush partial frames and return monitor to idle observe-only state and release sampling handles

## Questions

1. What LCR-controlled SYM_LINE_FORMAT including data_bits parity and stop_bits must the monitor use to delimit tx and rx frames?
2. What divisor-latch plus clock-period combination defines SYM_BIT_CYCLES and mid-bit sampling point for stx_pad_o and srx_pad_i reconstruction?
3. Which framing parity and break attributes must be attached to reconstructed tx and rx transactions and how is break-hold distinguished from idle?
4. What reset assertion level and sequencing must trigger monitor flush of partial frames and shift-register state and what pad idle state applies during reset?
5. How must tx and rx analysis streams be routed to downstream comparison without self-comparison and without including configuration traffic?

## Essential blockers


## Specification evidence

- `f_stx_dir` → `/interfaces/groups/5` / `CH-98be4510fb`
> STX_PAD_O 1 Output The serial output signal

- `f_srx_dir` → `/interfaces/groups/5` / `CH-98be4510fb`
> SRX_PAD_I 1 Input The serial input signal

- `f_uart_func` → `/interfaces/groups/5/property_evidence/function` / `CH-2baa4497c0`
> The UART (Universal Asynchronous Receiver/Transmitter) core provides serial
> communication capabilities

- `f_rs232_proto` → `/interfaces/groups/5/property_evidence/function` / `CH-2baa4497c0`
> like another computer using a serial cable and RS232 protocol

- `f_ext_conn` → `/interfaces/groups/5/property_evidence/function` / `CH-2baa4497c0`
> which allow communication with modem or other external
> devices
