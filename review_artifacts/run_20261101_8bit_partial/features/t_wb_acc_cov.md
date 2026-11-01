# Wishbone access coverage

Work package: `t_wb_acc_cov` · coverage · NEEDS_REVIEW

## Dependent features

- `t_wb_seq`: Wishbone direction acknowledge and DLAB gating coverage requires base register access stimulus.
- `t_wb_mon`: Wishbone access coverage sampling requires bus monitor reconstructed transactions.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_uart_cfg`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Plan wishbone_bus WISHBONE access coverage from monitor-reconstructed transactions for direction plus DLAB gating normal versus divisor. Reuse checked wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o identity map with RTL names for code. DOCUMENTED DLAB bit 7 and 8-bit responder role support partial DLAB mapping; QUICK_TEST_PLAN_APPROVAL address bins and ACK sampling stay INFERRED test-only not engineer sign-off and guide architecture only.

## Preconditions

1. Clock stable at selected period and reset deasserted via ordered bring-up
2. wishbone_bus monitor active reconstructing completed read and write transactions for subscriber tap
3. LCR DLAB bit 7 state observable for normal versus divisor classification
4. Base register access stimulus available via t_wb_seq and monitor via t_wb_mon dependencies

## Stimulus pseudocode

```text
1. FOR each symbolic phase in normal_DLAB0 then divisor_DLAB1: DRIVE LCR DLAB to documented 0 or 1 via wishbone_bus
2. DRIVE symbolic read and write operations via wishbone_bus to exercise shared versus other addresses for coverage
3. WAIT for wishbone_bus monitor to emit completed transaction before next stimulus
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. WAIT for wishbone_bus monitor analysis port to emit observed completed transaction with acknowledge indication [f_wb_8bit]
2. SAMPLE wb_direction from wb_we_i symbolic read versus write on completed transaction only; never sample driver stimulus
3. SAMPLE dlab_addr_map from address phase plus LCR DLAB bit 7 state distinguishing normal versus divisor at shared addresses [f_dlab_bit] [f_dlab_one] [f_dlab_zero]
4. SAMPLE cross wb_addr_x_dlab combining symbolic address with DLAB state for gating interaction
5. EXCLUDE idle cycles with no framing and unlisted gaps via ignore_bins; terminate sampling on completion timeout
```

## Completion

1. WAIT until all spawned sampling complete OR UNTIL SYM_TIMEOUT_CYCLES expires as TESTBENCH operational limit not DUT timing
2. DRAIN wishbone_bus monitor for SYM_DRAIN_CYCLES idle cycles for pipeline drain then close sampling
3. CLEANUP clear coverage sampling state and release observation handles with no driven bus changes

## Questions

1. Confirm documented wb_adr_i representation in DATA_BUS_WIDTH_8 build: 3-bit pin values for normal versus divisor and other registers, legality of addr 7, and 5-or-3 width handling?
2. What are active and idle levels of wb_we_i wb_stb_i wb_cyc_i wb_ack_o, transaction framing, single ACK rule, and sampling clock edge for direction and acknowledge coverage?
3. What is expected behavior of other addresses 2 to 6 while DLAB is 1, and of shared addresses 0 to 1 when gating blocks opposite mapping?
4. What is coverage DLAB state source and ordering: LCR mirror versus uart_config, set-then-clear around divisor access, and MSB-first LSB-next relevance?
5. What are legal ignore versus illegal bins for idle_no_stb_cyc, addr_7_unused, and unlisted gaps, and confirm per-instance false with wb_sel_i and data validity filtering?

## Essential blockers


## Specification evidence

- `f_dlab_bit` → `/registers/registers/7/fields/6` / `CH-bc7559f2ec`
> 7 RW Divisor Latch Access bit.

- `f_dlab_one` → `/registers/registers/7/fields/6` / `CH-bc7559f2ec`
> ‘1’ – The divisor latches can be accessed

- `f_dlab_zero` → `/registers/registers/7/fields/6` / `CH-bc7559f2ec`
> ‘0’ – The normal registers are accessed

- `f_wb_8bit` → `/sections/10/entries/3` / `CH-d62a4ba2db`
> It has an 8-bit data bus for compatibility reason.
