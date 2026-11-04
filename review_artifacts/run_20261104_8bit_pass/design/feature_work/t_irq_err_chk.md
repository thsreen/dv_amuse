# Interrupt and line-error checks

Work package: `t_irq_err_chk` · verification_plan · NEEDS_REVIEW

## Dependent features

- `t_lsr_status`: overrun parity framing break interrupt reporting builds on LSR status
- `t_irq_baud_mon`: enabled-source matching needs INT_O IIR observation

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_id_cov`, `t_line_err_cov`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Feature t_irq_err_chk checks int_o matches enabled IER sources with IIR highest-priority reporting and reset control plus LSR OE PE FE BI set per RX condition generating RLS interrupt cleared on LSR read. Entries 10-11 are QUICK_TEST inferred only not engineer approval. Depends on deferred t_lsr_status and passive t_irq_baud_mon int_o observation. Uses wishbone_slave_interface for register access uart_serial_data for RX error injection interrupt_output passive for int_o modem_control_if owned or tied off. Clock and reset are common UVCs.

## Preconditions

1. Clock runs at symbolic P_fixed; reset driven via reset with symbolic polarity and duration; expect IIR reset C1h no-pending [f_iir_reset f_iir_pend1]
2. DUT in DATA_BUS_WIDTH_8 FIFO-only mode; divisor and LCR line format programmed via wishbone_slave_interface to symbolic SYM_DIVISOR SYM_LCR matching uart_serial_data data_bits parity stop_bits bit_cycles
3. Input ownership on physical ports: wishbone_slave_interface owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i; uart_serial_data owns srx_pad_i; modem_control_if owns or ties off cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i; clock owns wb_clk_i; reset owns wb_rst_i; observe wb_dat_o wb_ack_o int_o stx_pad_o rts_pad_o dtr_pad_o; addresses are actual wb_adr_i pin values
4. interrupt_output passively observes int_o; wishbone reads observe IIR LSR; no driver forces int_o; entries 10 and 11 remain quick-test inferred only
5. Symbolic addresses SYM_ADDR_IER SYM_ADDR_IIR SYM_ADDR_LSR SYM_ADDR_RBR SYM_ADDR_THR SYM_ADDR_MSR and symbolic enables; LSR IER resets unknown null

## Stimulus pseudocode

```text
1. STAGE bringup: WAIT reset release; program SYM_DIVISOR SYM_LCR via wishbone_slave_interface; configure uart_serial_data to same data_bits parity stop_bits bit_cycles; READ IIR at SYM_ADDR_IIR to confirm C1h no-pending [f_iir_reset f_iir_pend1 f_int_single]
2. STAGE rls_inject: FOR err IN [overrun parity framing break]: IF err==overrun THEN fill RX FIFO via uart_serial_data then send extra char into shift register [f_oe_set]; IF err==parity THEN send char with inverted parity [f_pe_set]; IF err==framing THEN send char without valid stop [f_fe_set]; IF err==break THEN hold srx_pad_i at 0 for one char time [f_bi_set]
3. After each injection: WAIT RX complete; SAMPLE int_o via interrupt_output; READ LSR at SYM_ADDR_LSR via wishbone_slave_interface; READ IIR at SYM_ADDR_IIR [f_iir_highest f_iir_pend0 f_iir_rls f_lsr_clr_rls f_bi_clr]
4. STAGE priority_overlap: WRITE symbolic IER to enable RLS plus lower sources; create concurrent pending with RLS error plus THRE RDA timeout modem where reachable; READ IIR to observe highest priority 011 over 010_110 over 001 over 000 [f_iir_rls f_iir_rda f_iir_timeout f_iir_thre_src f_iir_thre_rst f_iir_modem]
5. STAGE reset_actions: apply documented resets: READ LSR for RLS [f_iir_rls f_lsr_clr_rls f_bi_clr]; WAIT FIFO drop below trigger for RDA [f_iir_rda]; READ RBR for timeout [f_iir_timeout]; WRITE THR or READ IIR for THRE [f_iir_thre_rst]; READ MSR for modem [f_iir_modem]; re-READ IIR to confirm next priority or no-pending
6. Cleanup: program symbolic FIFO reset; return srx_pad_i to idle; leave modem inputs tied off
```

## Check pseudocode

```text
1. COMPARE int_o asserted exactly when pending source enabled by symbolic IER and IIR bit0==0; int_o negated when IIR bit0==1; FAIL on spurious or missing [f_int_single f_iir_pend0 f_iir_pend1 f_iir_highest]
2. COMPARE IIR bits 3-1 highest priority 011 RLS first over 010/110 second over 001 third over 000 fourth; FAIL on mis-prioritized; COMPARE fixed bits 7-6==11 and 5-4==00 [f_iir_rls f_iir_rda f_iir_timeout f_iir_thre_src f_iir_modem f_iir_fixed67 f_iir_fixed45]
3. COMPARE LSR OE set iff FIFO full plus extra char in shift register; PE set iff top char parity error; FE set iff top char no valid stop; BI set iff break hold 0 for one char time [f_oe_set f_pe_set f_fe_set f_bi_set]
4. COMPARE OE PE FE BI generate Receiver Line Status interrupt with IIR 011; FAIL on lost or aliased indication [f_iir_rls f_lsr_clr_rls f_bi_clr]
5. COMPARE OE PE FE BI cleared upon LSR read; RLS reset by LSR read advances IIR to next pending or to 1 no-pending; FAIL on sticky [f_lsr_clr_rls f_bi_clr f_iir_rls f_iir_pend1]
6. COMPARE THRE RDA timeout modem resets only as documented; use operational timeouts as testbench limits not DUT timing [f_iir_rda f_iir_timeout f_iir_thre_rst f_iir_modem]
```

## Coverage pseudocode

```text
1. SAMPLE cg_iir_interrupt cp_iir_pending pending_0 no_pending_1 on every IIR read completion via wishbone monitor tap [f_iir_pend0 f_iir_pend1]
2. SAMPLE cp_iir_code 011_rls 010_rda 110_timeout 001_thre 000_modem and illegal 100_101_111 on same tap; SAMPLE cp_iir_fixed 76_11 and 54_00 [f_iir_rls f_iir_rda f_iir_timeout f_iir_thre_src f_iir_modem f_iir_fixed67 f_iir_fixed45]
3. SAMPLE each LSR error assertion OE PE FE BI on LSR read via wishbone monitor tap; SAMPLE RLS assertion and clearing via interrupt_output monitor tap [f_oe_set f_pe_set f_fe_set f_bi_set f_lsr_clr_rls f_bi_clr]
4. Dedicated subscribers tap monitor analysis ports; drivers never supply coverage; virtual spawn only with no VIFs or delays
```

## Completion

1. End after each RLS kind observed set plus RLS interrupt plus clear-on-read and priority overlap with reset sequence done plus drain_cycles flush
2. Abort on request_timeout_cycles operational limit; timeout is testbench limit not DUT timing
3. Require at least one scoreboard comparison per test; basic single-error functional test first then overlap tests

## Questions

1. What are documented IER bit assignments mapping RLS RDA Timeout THRE Modem enables to INT_O gating?
2. What are actual wb_adr_i pin values for IER IIR LSR RBR THR FCR LCR DLL DLM MSR accesses?
3. What is documented INT_O polarity and inactive level for assertion versus deassertion?
4. What is active level polarity of wb_rst_i and required reset duration in clock cycles to clear IIR LSR pending?
5. What is nominal fixed clock period P_fixed for timestamping INT_O IIR LSR events?
6. What are documented divisor LCR and FIFO trigger programming values and matching uart_serial_data data_bits parity stop_bits bit_cycles for each error injection?
7. What are FIFO depth and fill counts for overrun and hold duration in char times for break injection?
8. What are documented reset values for LSR and IER; is unknown reset null?

## Essential blockers


## Specification evidence

- `f_iir_highest` → `/sections/8/entries/4` / `CH-f91cbf1c05`
> The IIR enables the programmer to retrieve what is the current highest priority pending

- `f_iir_pend0` → `/sections/8/entries/3` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’.

- `f_iir_pend1` → `/sections/8/entries/3` / `CH-f91cbf1c05`
> When it’s ‘1’ – no interrupt
> is pending.

- `f_iir_rls` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Parity, Overrun or Framing
> errors or Break Interrupt
> Reading the Line
> Status Register

- `f_iir_rda` → `/sections/8/entries/4` / `CH-f91cbf1c05`
> FIFO trigger level reached FIFO drops below
> trigger level

- `f_iir_timeout` → `/sections/8/entries/4` / `CH-f91cbf1c05`
> There’s at least 1 character
> in the FIFO but no character
> has been input to the FIFO
> or read from it for the last 4
> Char times.
> Reading from the
> FIFO (Receiver
> Buffer Register)

- `f_iir_thre_src` → `/sections/8/entries/4` / `CH-f91cbf1c05`
> Transmitter Holding
> Register Empty

- `f_iir_thre_rst` → `/sections/8/entries/4` / `CH-f91cbf1c05`
> Writing to the
> Transmitter Holding
> Register or reading
> IIR.

- `f_iir_modem` → `/sections/8/entries/4` / `CH-f91cbf1c05`
> CTS, DSR, RI or DCD. Reading the Modem
> status register.

- `f_iir_fixed67` → `/sections/9/entries/2` / `CH-f91cbf1c05`
> Bits 6 and 7: Logic ‘1’ for compatibility reason.

- `f_iir_fixed45` → `/sections/9/entries/2` / `CH-f91cbf1c05`
> Bits 4 and 5: Logic ‘0’.

- `f_iir_reset` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Reset Value: C1h

- `f_int_single` → `/sections/4/strategy/agents/3` / `CH-d62a4ba2db`
> The core requires one interrupt.

- `f_oe_set` → `/registers/registers/9/fields/1` / `CH-a2dd758e55`
> If the FIFO is full and another character has been
> received in the receiver shift register.

- `f_pe_set` → `/registers/registers/9/fields/2` / `CH-a2dd758e55`
> The character that is currently at the top of the FIFO
> has been received with parity error.

- `f_fe_set` → `/registers/registers/9/fields/3` / `CH-a2dd758e55`
> The received character at the top of the FIFO did not
> have a valid stop bit.

- `f_bi_set` → `/registers/registers/9/fields/4` / `CH-a2dd758e55`
> The break occurs when the line is held in logic 0 for a
> time of one character (start bit + data + parity + stop bit).

- `f_bi_clr` → `/registers/registers/9/fields/4` / `CH-a2dd758e55`
> The bit is cleared upon
> reading from the register. Generates Receiver Line Status interrupt.

- `f_lsr_clr_rls` → `/sections/8/entries/6` / `CH-a2dd758e55`
> The bit is cleared upon reading from the register.
> Generates Receiver Line Status interrupt.
