# Serial traffic sequences

Work package: `t_serial_seq` · sequence · NEEDS_REVIEW

## Dependent features

- None identified.

## Independent features

`t_bringup_clk`, `t_clk_cov`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_shared_dir`, `t_uart_cfg`, `t_wb_acc_cov`, `t_wb_mon`, `t_wb_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Serial traffic on serial_data driving srx_pad_i and observing stx_pad_o with normal break idle children under serial_traffic serial_top coordinated via virtual spawn. DOCUMENTED authority covers LCR reset default per f_lcr_reset_1 divisor zero per f_div_reset_1 and break hold zero-character semantics per f_break_dur_1 f_break_fifo_1. Line-format encodings divisor mapping and idle rules stay symbolic. QUICK_TEST_PLAN_APPROVAL intentions stay INFERRED test-only; QUICK_TEST_AUTO_APPROVAL idle is test-only infra.

## Preconditions

1. clock stable at fixed period per test with no dynamic change during traffic and reset deasserted with monitor flushed; describe clock and reset directly without naming agents
2. wishbone_bus divisor and LCR programming completed before serial traffic with transmission engine enabled per f_lcr_reset_1 and f_div_reset_1 defaults; concrete data_bits parity stop_bits divisor values remain symbolic pending DOCUMENTED encodings
3. serial_data active agent owns srx_pad_i drive and stx_pad_o observe per checked spec-to-RTL map using RTL names srx_pad_i and stx_pad_o; no other agent drives srx_pad_i
4. quick-testing only infra binding with srx_pad_i idle 1 is TESTBENCH choice not DUT oracle; driver and monitor bit_cycles kept consistent symbolically

## Stimulus pseudocode

```text
1. STAGE0 directed bring-up on serial_data sequencer: SEND normal_frame with symbolic default format driving srx_pad_i while SAMPLE stx_pad_o; WAIT frame completion; CLEANUP return to idle
2. STAGE1 random traffic: FOR num_frames iterations with reproducible seed: RANDOMLY SELECT child among normal_frame break_hold idle_gap; IF normal_frame THEN SEND symbolic byte payload length parity stop; ELSE IF break_hold THEN HOLD srx_pad_i low for symbolic break duration per f_break_dur_1; ELSE HOLD idle for symbolic gap; WAIT inter-frame gap
3. Pass serial_data sequencer handle explicitly to every send call; per-agent sequence drives only srx_pad_i and observes only stx_pad_o with bit timing derived symbolically from programmed divisor and fixed clock period
4. Coordinate from top-level virtual sequence via explicit handles to serial_data wishbone_bus modem_control_if sequencers: virtual sequence SPAWNs serial_top and configuration sequences concurrently in ordered stages; virtual sequence does no VIF access and uses no delays
```

## Check pseudocode

```text
1. COMPARE break_hold observation against DOCUMENTED break semantics per f_break_dur_1 and f_break_fifo_1: HOLD srx_pad_i low for one character time then SAMPLE monitor rx queue for single zero character and wait for valid start; never compare an event with itself; rx is DUT input and tx is DUT output
2. DEFER payload framing parity value checks pending source-supported LCR character length parity stop_bits encodings; no parity framing stop assertion emitted without DOCUMENTED support
```

## Coverage pseudocode

```text
1. SAMPLE dedicated subscriber tapping serial_data monitor analysis ports for child selection normal_frame versus break_hold versus idle_gap and direction tx versus rx; drivers never supply coverage events
2. SAMPLE symbolic line-format bins data_bits parity stop_bits inter_frame_gap as architectural placeholders only pending DOCUMENTED encodings
```

## Completion

1. WAIT until num_frames completions observed on serial_data monitor analysis ports or request_timeout_cycles expires as TESTBENCH operational limit only
2. DRAIN residual bits for drain_cycles then return srx_pad_i to test-only idle; on reset FLUSH partial frames and shift state; REPORT seed and num_frames knob; CLEANUP release sequencer handles

## Questions

1. Confirm source-supported frame formats for serial children: LCR character length parity stop-bit encodings and legal values?
2. Confirm divisor to bit_cycles mapping including Input Clock Speed Divisor equals 16x baud formula and clock period binding?
3. Confirm idle-gap duration mark idle level and inter-frame gap rules with DOCUMENTED authority beyond quick-test auto-approval?
4. Confirm SRX-to-THR timing and inter-frame gap sampling rules for serial traffic?
5. Confirm complete LCR stick parity definition when bits 3 and 4 are logic 1 and unspecified upper bits?

## Essential blockers


## Specification evidence

- `f_lcr_reset_1` → `/sections/5/entries/10` / `CH-1e2324cfc3`
> The Line Control Register is set to communication of 8 bits of data, no parity, 1

- `f_div_reset_1` → `/sections/5/entries/11` / `CH-1e2324cfc3`
> The Divisor Latch register is set to 0.

- `f_break_dur_1` → `/registers/registers/9/fields/4` / `CH-a2dd758e55`
> time of one character (start bit + data + parity + stop bit)

- `f_break_fifo_1` → `/registers/registers/9/fields/4` / `CH-a2dd758e55`
> one zero character enters the FIFO and the UART waits for a
