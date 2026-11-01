# Reset FIFO and LCR checks

Work package: `t_reset_fifo_lcr` · check · NEEDS_REVIEW

## Dependent features

- `t_bringup_clk`: FIFO cleared and LCR reset checks require completed power-on reset coordination.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_uart_cfg`, `t_wb_acc_cov`, `t_wb_mon`, `t_wb_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Verify after t_bringup_clk reset that RX and TX FIFOs plus shift registers are cleared and LCR reads 00000011b for 8 bits no parity 1 stop before uart_config, reporting stale data or LCR mismatch as reset failure.

## Preconditions

1. Power-on reset coordination from t_bringup_clk complete with reset deasserted under SYM_RESET_POLARITY plus SYM_IDLE_CYCLES clock cycles on wb_clk_i
2. Clock period fixed per test as SYM_CLK_PERIOD with no dynamic change during checks
3. No uart_config programming before reset-value readback; checks run before init traffic
4. wishbone_bus owned for reads; serial_data held idle with no rx injection; modem_control_if held at maintained idle

## Stimulus pseudocode

```text
1. WAIT for reset deassertion under SYM_RESET_POLARITY plus SYM_IDLE_CYCLES clock cycles on wb_clk_i
2. wishbone_bus: READ LCR via wb_adr_i equals 3 and SAMPLE wb_dat_o width 8 per f_lcr_addr
3. wishbone_bus: READ FIFO status via SYM_LSR_ADDR and attempt SYM_RBR_ADDR read with no prior traffic and SAMPLE results per f_fifo_check
4. serial_data: HOLD srx_pad_i at maintained idle and OBSERVE stx_pad_o idle to expose uncleared shift bits per f_shift_clear
5. modem_control_if: HOLD inputs at maintained idle without assuming inactive level
```

## Check pseudocode

```text
1. COMPARE LCR read data masked 0xFF against 00000011b expecting 8 bits no parity 1 stop per f_lcr_expect and f_lcr_reset; IF mismatch THEN report LCR reset-value failure
2. COMPARE LCR bit2 equals 0 meaning 1 stop bit per f_stop_1; IF not 0 THEN report LCR reset-value failure
3. COMPARE Transmit FIFO empty indicator equals 1 meaning transmitter FIFO empty per f_tx_empty; IF 0 THEN report reset failure
4. COMPARE no stale Receiver Buffer data readable before init traffic per f_fifo_check and f_fifo_cleared; IF any byte readable THEN report reset failure; IF observation address unavailable THEN record q_rx_addr gap
```

## Coverage pseudocode

```text
1. SAMPLE wishbone_bus monitor LCR readback value and reset-match result for reset-value coverage
2. SAMPLE wishbone_bus monitor FIFO-status reads for TX-empty and RX-empty attempt for reset coverage
3. SAMPLE serial_data monitor idle observation during reset window for shift-clear coverage per f_shift_clear
```

## Completion

1. WAIT for all wishbone_bus read completions plus SYM_DRAIN_CYCLES clock cycles on wb_clk_i then declare checks done
2. ENFORCE TEST_TIMEOUT_CYCLES as testbench operational limit not DUT timing
3. CLEANUP return wishbone_bus and serial_data and modem_control_if to idle and release coordination handles

## Questions

1. What bus addresses and masks observe receiver-empty and transmitter-empty after reset, since only LCR address 3 and TX-empty semantics are documented?
2. What is expected Receiver Buffer read behavior when FIFOs are empty to define stale-data failure without guessing?
3. What are evidenced idle tie-off levels and owners for srx_pad_i cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and wb_sel_i wb_we_i wb_stb_i wb_cyc_i during readback?
4. Is FCR clear sequencing required before FIFO-empty checks and what is documented RX clear encoding versus TX bit2 clear?
5. How is shift-register cleared status observed and what serial_data monitor data_bits parity stop_bits apply for reset 8N1 idle?

## Essential blockers


## Specification evidence

- `f_fifo_check` → `/sections/5/entries/9` / `CH-1e2324cfc3`
> • The receiver and transmitter FIFOs are cleared.

- `f_lcr_expect` → `/sections/5/entries/10` / `CH-1e2324cfc3`
> • The Line Control Register is set to communication of 8 bits of data, no parity, 1
> stop bit.

- `f_fifo_cleared` → `/sections/1/entries/9` / `CH-1e2324cfc3`
> Upon reset the core performs the following tasks:
> 
> • The receiver and transmitter FIFOs are cleared.

- `f_shift_clear` → `/sections/1/entries/10` / `CH-1e2324cfc3`
> • The receiver and transmitter shift registers are cleared

- `f_lcr_addr` → `/registers/registers/7` / `CH-f88915355b`
> Line Control Register 3 8 RW Control connection

- `f_lcr_reset` → `/registers/registers/7` / `CH-bc7559f2ec`
> Reset Value: 00000011b

- `f_stop_1` → `/registers/registers/7/fields/1` / `CH-bc7559f2ec`
>  ‘0’ – 1 stop bit

- `f_tx_empty` → `/registers/registers/9/fields/5` / `CH-a2dd758e55`
>  ‘1’ – The transmitter FIFO is empty.

- `f_fcr_tx_clear` → `/registers/registers/5/fields/2` / `CH-dfb1048908`
> Writing a ‘1’ to bit 2 clears the Transmitter FIFO and resets its
> logic.
