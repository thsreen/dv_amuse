# IER reset checks

Work package: `t_ier_reset` · check · NEEDS_REVIEW

## Dependent features

- `t_bringup_clk`: IER disabled after reset check requires completed reset sequence before Wishbone read.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_iir_cov`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_uart_cfg`, `t_wb_acc_cov`, `t_wb_mon`, `t_wb_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Verify IER shows all interrupts disabled after reset with value 00h and bits 7-4 remain zero via masked Wishbone read.

## Preconditions

1. WAIT for t_bringup_clk reset coordination completed before Wishbone read
2. Clock stable and wishbone_bus idle and ready for register access
3. Use symbolic SYM_IER_ADDR for IER access without inventing bus value

## Stimulus pseudocode

```text
1. WAIT for t_bringup_clk reset deassertion completion
2. READ IER via wishbone_bus at SYM_IER_ADDR yielding IER_RDATA [f_ier_reset_value]
```

## Check pseudocode

```text
1. COMPARE (IER_RDATA AND 0xFF) TO 0x00 for all-disabled reset [f_ier_disabled, f_ier_reset_value]
2. COMPARE (IER_RDATA AND 0xF0) TO 0x00 for reserved bits 7-4 remain zero [f_ier_reserved_zero]
3. USE explicit masks 0xFF and 0xF0 with expected 0x00 and null mirror unknown; never invent zero for unknown
```

## Coverage pseudocode

```text
```

## Completion

1. DECLARE pass iff both masked compares match with zero scoreboard mismatches
2. ENFORCE TEST_TIMEOUT_CYCLES as testbench operational limit not DUT timing
3. CLEANUP return wishbone_bus to idle

## Questions

1. What is the expected WISHBONE write and read behavior for IER bits 7-4 when written to 1, including whether they are stored, returned on read, or affect interrupt generation?

## Essential blockers


## Specification evidence

- `f_ier_disabled` → `/sections/1/entries/11` / `CH-1e2324cfc3`
> All interrupts are disabled in the Interrupt Enable Register.

- `f_ier_reset_value` → `/sections/8/entries/3` / `CH-de51b2eafc`
> Reset Value: 00h

- `f_ier_reserved_zero` → `/registers/registers/4/fields/4` / `CH-de51b2eafc`
> 7-4 RW Reserved. Should be logic ‘0’.
