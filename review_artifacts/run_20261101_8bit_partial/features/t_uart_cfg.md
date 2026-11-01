# UART configuration sweep

Work package: `t_uart_cfg` · configuration · NEEDS_REVIEW

## Dependent features

- `t_bringup_clk`: UART LCR divisor FIFO IER programming requires stable clock and completed reset bring-up before any register access.
- `t_wb_seq`: Configuration sweep reuses Wishbone DLAB-gated divisor register read and write base sequences for directed and random programming.

## Independent features

`t_clk_cov`, `t_ier_reset`, `t_iir_cov`, `t_modem_seq`, `t_obs_mon`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_wb_acc_cov`, `t_wb_mon`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Temporary quick-testing contract for uart_config: program LCR format, DLAB-gated divisor MSB-first LSB-next, FIFO trigger and IER in dependency order via wishbone_bus after clock and reset bring-up, with directed corners then symbolic sweep; all QUICK_TEST_PLAN_APPROVAL details remain INFERRED, not engineer approval.

## Preconditions

1. Clock is stable at selected period and reset bring-up from t_bringup_clk is complete with idle cycles observed
2. wishbone_bus base read write and DLAB-gated divisor sequences from t_wb_seq are available via explicit wishbone_bus sequencer handle
3. DUT is in DATA_BUS_WIDTH_8 build with 3-bit wb_adr_i and 8-bit data; uart_config virtual sequence runs on virtual sequencer with no VIFs or delays
4. QUICK_TEST_PLAN_APPROVAL intentions are INFERRED temporary test-only approvals, not engineer sign-off; only quoted source text constrains behavior

## Stimulus pseudocode

```text
1. WAIT for t_bringup_clk completion THEN OBTAIN explicit handle to wishbone_bus sequencer; START uart_config on null virtual sequencer with sequencer-handle switch and no VIFs or delays with timing tracked to selected clock period
2. FOR directed bring-up corners via wishbone_bus sequencer only in dependency order per f_dlab_set_1 to f_ier_step_5: WRITE LCR at 3 with DLAB 1 THEN WRITE divisor MSB at 1 first THEN LSB at 0 THEN WRITE LCR at 3 with DLAB 0 THEN WRITE FCR at 2 with trigger THEN WRITE IER at 1; INCLUDE reset-all-disabled with IER 0, max-trigger 11, and DLAB-set-blocking-normal-0to1 case
3. FOR sweep over SYM_LCR_CHAR SYM_STOP SYM_PARITY SYM_DIV_MSB SYM_DIV_LSB SYM_TRIG SYM_IER under set-then-clear DLAB constraint: SPAWN wishbone_bus write and read children per iteration; per-agent sequences drive only wishbone_bus interface
4. IF serial_data or modem_control_if traffic is required THEN SPAWN only their own agents separately; uart_config virtual sequence itself drives nothing directly
```

## Check pseudocode

```text
1. COMPARE DLAB gating per f_dlab_block_6 and f_dlab_gate_7: IF DLAB is 1 THEN only divisor LSB at addr 0 and MSB at addr 1 are routed AND normal RB_THR at 0 and IER at 1 are blocked; IF DLAB is 0 THEN reverse
2. COMPARE LCR readback per f_lcr_read_22: WAIT wishbone_bus read at addr 3 THEN COMPARE observed data equals programmed format for sampled LCR values
3. COMPARE divisor and IER persistence: WAIT wishbone_bus read of divisor LSB_MSB with DLAB 1 and IER with DLAB 0 THEN COMPARE observed data equals last programmed SYM_DIV and SYM_IER excluding FCR which is write-only
```

## Coverage pseudocode

```text
1. SAMPLE cg_divisor per f_divlsb_addr_11 and f_divmsb_addr_12 via dedicated subscriber tapping wishbone_bus monitor analysis port on divisor write with DLAB set: bins zero max mid_low mid_high
2. SAMPLE dlab_addr_map and wb_addr_x_dlab per f_dlab_block_6 and f_dlab_gate_7 via dedicated subscriber tapping wishbone_bus monitor on ACK with DLAB state: normal_0_DLAB0 normal_1_DLAB0 divlsb_0_DLAB1 divmsb_1_DLAB1 other_2to6
3. SAMPLE LCR format per f_lcr_char_13, FCR trigger per f_fcr_trigvals_17 and IER enables per f_ier_bits_18 via dedicated subscriber tapping wishbone_bus monitor analysis port; drivers never supply coverage
```

## Completion

1. WAIT all spawned wishbone_bus children complete OR UNTIL TESTBENCH request_timeout_cycles expires as operational limit only
2. DRAIN wishbone_bus monitor for drain_cycles as TESTBENCH operational limit then close uart_config virtual sequence
3. CLEANUP deassert wb_stb_i and wb_cyc_i via wishbone_bus driver, return wishbone_bus to idle, release explicit sequencer handles, leave serial_data and modem_control_if untouched

## Questions

1. Confirm legal LCR, divisor, trigger and IER values and programming order including character-length stop parity stick break combinations, divisor zero legality, and MSB-first LSB-next with set-then-clear DLAB?
2. Are write and read addresses literal 3-bit wb_adr_i pin values 0 to 6 with LCR at 3 FCR at 2 IER at 1 divisor LSB at 0 MSB at 1, what is legality of addr 7, and does DLAB 1 route 0 to LSB and 1 to MSB while blocking normal 0 to 1?
3. What is active level of wb_rst_i and inactive levels of wb_stb_i wb_cyc_i wb_we_i, what is legal wb_sel_i with 4-bit sel and 8-bit data, and what are request_timeout_cycles drain_cycles and WB_ACK_O latency plus back-to-back idle rule for config accesses?
4. What are constrained-random legal masks and comparison masks for LCR IER FCR divisor given DLAB-banked fields, and how are reserved IER 7-4 and write-only FCR handled in mirrors and scoreboards?
5. How must serial_data data_bits parity stop_bits and bit_cycles track the LCR sweep, and must configuration bus writes agree with serial driver and monitor settings?
6. What are owners or tie_offs for all DUT inputs during uart_config: wishbone_bus drives WB inputs, but what drives srx_pad_i cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and observes stx_pad_o rts_pad_o dtr_pad_o int_o?
7. How do sweep_level knob, seeds, uniform exhaustive versus corner-biased reset-all-disabled and max-trigger cases, and predictor update for configured divisor and line state scale combinations?

## Essential blockers


## Specification evidence

- `f_dlab_set_1` → `/sections/5/entries/4` / `CH-1e2324cfc3`
> Set bit 7 to ‘1’
> to allow access to the Divisor Latches.

- `f_div_order_2` → `/sections/5/entries/4` / `CH-1e2324cfc3`
> Set the Divisor Latches, MSB first, LSB next.

- `f_dlab_clear_3` → `/sections/5/entries/4` / `CH-1e2324cfc3`
> Set bit 7 of LCR to ‘0’ to disable access to Divisor Latches.

- `f_fifo_step_4` → `/sections/5/entries/4` / `CH-1e2324cfc3`
> Set the FIFO trigger level.

- `f_ier_step_5` → `/sections/5/entries/4` / `CH-1e2324cfc3`
> Enable desired interrupts by setting appropriate bits in the Interrupt Enable
> register.

- `f_dlab_block_6` → `/sections/7/entries/4` / `CH-f88915355b`
> At this time the above registers at addresses 0-1 can’t be accessed.

- `f_dlab_gate_7` → `/sections/9/entries/6` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set
> to ‘1’.

- `f_lcr_addr_8` → `/sections/6/configurations/10` / `CH-f88915355b`
> Line Control Register 3 8 RW Control connection

- `f_fcr_addr_9` → `/sections/6/configurations/9` / `CH-f88915355b`
> FIFO Control 2 8 W Control FIFO options

- `f_ier_addr_10` → `/sections/6/configurations/2` / `CH-f88915355b`
> Interrupt Enable 1 8 RW Enable/Mask interrupts

- `f_divlsb_addr_11` → `/sections/9/entries/4` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor

- `f_divmsb_addr_12` → `/sections/9/entries/4` / `CH-f88915355b`
> Divisor Latch Byte 2 1 8 RW The MSB of the divisor

- `f_lcr_char_13` → `/sections/6/configurations/10` / `CH-bc7559f2ec`
> 1-0 RW Select number of bits in each character

- `f_lcr_dlabbit_14` → `/sections/6/configurations/14` / `CH-bc7559f2ec`
> 7 RW Divisor Latch Access bit.

- `f_lcr_dlabvals_15` → `/sections/6/configurations/14` / `CH-bc7559f2ec`
> ‘1’ – The divisor latches can be accessed
>  ‘0’ – The normal registers are accessed

- `f_fcr_trig_16` → `/sections/6/configurations/9` / `CH-dfb1048908`
> 7-6 W Define the Receiver FIFO Interrupt trigger level

- `f_fcr_trigvals_17` → `/sections/6/configurations/9` / `CH-dfb1048908`
> ‘00’ – 1 byte
>  ‘01’ – 4 bytes
>  ‘10’ – 8 bytes
>  ‘11’ – 14 bytes

- `f_ier_bits_18` → `/sections/6/configurations/2` / `CH-de51b2eafc`
> 0 RW Received Data available interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled
> 1 RW Transmitter Holding Register empty interrupt

- `f_ier_bits2_19` → `/sections/6/configurations/4` / `CH-de51b2eafc`
> 2 RW Receiver Line Status Interrupt

- `f_ier_bits3_20` → `/sections/6/configurations/5` / `CH-de51b2eafc`
> 3 RW Modem Status Interrupt

- `f_ier_reserved_21` → `/sections/6/configurations/3` / `CH-de51b2eafc`
> 7-4 RW Reserved. Should be logic ‘0’.

- `f_lcr_read_22` → `/sections/6/configurations/12` / `CH-bc7559f2ec`
> Reading from the register is allowed to check the current
> settings of the communication.
