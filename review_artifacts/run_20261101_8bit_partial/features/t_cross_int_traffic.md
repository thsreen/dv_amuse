# Cross interrupt traffic coverage

Work package: `t_cross_int_traffic` · coverage · NEEDS_REVIEW

## Dependent features

- `t_loopback_stage`: Interrupt with RX-TX line-error modem cross requires staged interaction traffic first.

## Independent features

`t_clk_cov`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_shared_dir`, `t_traffic_err`, `t_wb_acc_cov`, `t_wb_mon`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

t_cross_int_traffic provides interaction coverage reusing t_loopback_stage traffic vehicle. DOCUMENTED authority is IIR type priority reset, IER 0-3 gating and FE indication; INFERRED cross_iir_ier and cross_transfer_error_modem definitions remain navigation only with INFERRED provenance. All addresses, serial format, modem clearing, reset polarity and levels stay symbolic pending questions.

## Preconditions

1. Clock running at fixed test period and reset applied then released with polarity symbolic unknown; wb_clk_i driven by clock and wb_rst_i driven by reset, all other DUT inputs owned below with symbolic idle levels per f_ier_reset f_iir_reset
2. wishbone_bus owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i and observes wb_dat_o wb_ack_o using wb_adr_i pin values symbolic; serial_data owns srx_pad_i and observes stx_pad_o; modem_control_if owns cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and observes rts_pad_o dtr_pad_o; uart_interrupt observes int_o
3. IER image starts at reset 00h all-disabled per f_ier_reset and IIR at C1h no-pending per f_iir_reset f_iir_pending; IER bits 0-3 gating per f_ier_gate f_ier_rx f_ier_thre f_ier_line f_ier_modem and IIR types per f_iir_ident
4. Dedicated coverage subscribers tap analysis ports of wishbone_bus serial_data modem_control_if uart_interrupt; drivers never supply coverage events; t_loopback_stage vehicle ready with DOCUMENTED reliance only on DR occupancy and IIR priority

## Stimulus pseudocode

```text
1. BRINGUP: APPLY reset then PROGRAM symbolic IER all-disabled via wishbone_bus own-interface writes per f_ier_reset f_ier_gate; VERIFY IIR shows no-pending per f_iir_pending f_iir_reset
2. FOR each DOCUMENTED IIR type line_status rx_data timeout thre modem per f_iir_ident f_iir_line f_iir_modem DO FOR each DOCUMENTED IER mask enabled masked plus all-disabled reset per f_ier_gate DO SPAWN wishbone_bus child for symbolic THR write or Receiver Buffer read AND SPAWN serial_data child for srx_pad_i frame AND SPAWN modem_control_if child for single toggle in same window; virtual sequence spawns only with no delays
3. IF framing-error window THEN DRIVE serial frame lacking valid stop bit per f_lsr_fe to create DOCUMENTED FE; ELSE DRIVE clean frame; DO NOT drive undocumented parity overrun break trigger overrun-full as expected behavior
4. WAIT all spawned wishbone_bus serial_data modem_control_if children complete OR UNTIL request_timeout_cycles expires as TESTBENCH operational limit only
```

## Check pseudocode

```text
1. COMPARE uart_interrupt observed int_o gating against DOCUMENTED IER enable per f_ier_gate f_ier_rx f_ier_thre f_ier_line f_ier_modem: IF corresponding bit is 1 enabled THEN ALLOW that source pending ELSE EXPECT masking; polarity symbolic pending question
2. COMPARE wishbone_bus observed IIR value against DOCUMENTED type priority and reset control per f_iir_ident f_iir_line f_iir_modem: line_status cleared by LSR read and modem cleared by Modem status read
```

## Coverage pseudocode

```text
1. SAMPLE cross_iir_ier via dedicated subscriber tapping uart_interrupt plus wishbone_bus IER state on int_o observation; COVER DOCUMENTED IIR types crossed with DOCUMENTED enabled masked including all-disabled reset per f_iir_ident f_iir_pending f_ier_reset; INFERRED bin labels navigation only, per-instance false
2. SAMPLE cross_transfer_error_modem via dedicated subscribers tapping serial_data plus wishbone_bus plus modem_control_if on Receiver Buffer or THR transfer with LSR error and modem toggle in same window; COVER only DOCUMENTED framing-error class per f_lsr_fe with symbolic parity overrun break trigger-full concurrent extensions; per-instance false
```

## Completion

1. WAIT all spawned sequences complete OR UNTIL request_timeout_cycles expires as TESTBENCH operational limit only, not DUT timing
2. DRAIN wishbone_bus plus serial_data plus modem_control_if plus uart_interrupt monitors for drain_cycles as TESTBENCH operational limit then close virtual sequence with no delays in virtual sequence
3. CLEANUP release explicit virtual sequencer handles, return wishbone_bus to symbolic idle without assuming wb_stb_i wb_cyc_i wb_we_i inactive levels, leave serial_data and modem_control_if at symbolic idle

## Questions

1. What are DOCUMENTED wb_adr_i pin values for Receiver Buffer THR IER IIR LSR Modem Status and Divisor Latch bytes, DLAB gating for 0-1, access types, and legality of addr 7 in DATA_BUS_WIDTH_8 build?
2. What is active level of wb_rst_i and inactive levels of wb_stb_i wb_cyc_i wb_we_i, legal wb_sel_i for 8-bit data, WB_ACK_O latency, back-to-back idle rule, and TESTBENCH request_timeout_cycles drain_cycles clock period values?
3. What are DOCUMENTED legal LCR format divisor FIFO trigger and IER programming order including DLAB set-then-clear, and how do configuration bus writes agree with serial_data data_bits parity stop_bits bit_cycles settings?
4. What is DOCUMENTED INT_O assertion polarity level persistence, priority arbitration among line_status rx_data timeout thre modem, no-pending encoding, and which register access clears each source beyond line_status LSR read and modem MSR read?
5. What are DOCUMENTED LSR DR OE PE BI error-summary semantics, overrun during full, break hold of one character time, FIFO trigger reached value, read-clear masks and comparison masks excluding configuration writes from payload routes?
6. What are DOCUMENTED Modem Status register bits and clearing, which CTS DSR RI DCD toggle generates modem status, modem toggle window definition versus serial byte, and inactive idle levels plus tie_offs for srx_pad_i cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i?
7. Confirm masking bins line_status_enabled masked rx_data_enabled masked timeout_enabled masked thre_enabled masked modem_enabled masked no_pending_any_mask and concurrent bins rx_clean_no_modem rx_parity_with_modem rx_framing_with_modem rx_overrun_full rx_break_hold tx_empty_concurrent_rx tx_write_during_error?
8. What are DOCUMENTED comparison masks and mirror handling for THR write-only Receiver Buffer read-only LSR IIR read-clear given side-effect banked behavior, and can payload integrity compare only completed write versus read queues filtered by origin address?

## Essential blockers


## Specification evidence

- `f_iir_ident` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> The IIR enables the programmer to retrieve what is the current highest priority pending
> interrupt.

- `f_iir_pending` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’.

- `f_iir_line` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Parity, Overrun or Framing
> errors or Break Interrupt
> Reading the Line
> Status Register

- `f_iir_modem` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 0 0 4 th Modem Status CTS, DSR, RI or DCD. Reading the Modem
> status register.

- `f_iir_reset` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Reset Value: C1h

- `f_ier_gate` → `/sections/8/entries/4` / `CH-de51b2eafc`
> This register allows enabling and disabling interrupt generation by the UART.

- `f_ier_rx` → `/sections/8/entries/4` / `CH-de51b2eafc`
> 0 RW Received Data available interrupt

- `f_ier_thre` → `/sections/8/entries/4` / `CH-de51b2eafc`
> 1 RW Transmitter Holding Register empty interrupt

- `f_ier_line` → `/registers/registers/4/fields/2` / `CH-de51b2eafc`
> 2 RW Receiver Line Status Interrupt

- `f_ier_modem` → `/registers/registers/4/fields/3` / `CH-de51b2eafc`
> 3 RW Modem Status Interrupt

- `f_ier_reset` → `/sections/8/entries/4` / `CH-de51b2eafc`
> Reset Value: 00h

- `f_lsr_fe` → `/registers/registers/9/fields/3` / `CH-a2dd758e55`
> The received character at the top of the FIFO did not
> have a valid stop bit.
