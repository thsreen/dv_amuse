# Line-status and error cross

Work package: `t_line_err_cov` · coverage · NEEDS_REVIEW

## Dependent features

- `t_uart_mon`: line-status error cross needs serial transfer observation

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Cover LSR Data Ready Overrun Parity Framing and Break via LSR reads and cross THR writes and RBR reads with concurrent LSR errors for data plus error reporting.

## Preconditions

1. RESET_AND_DEPENDENCY: WAIT for common clock stable and common reset to reach inactive level with polarity and deassert to first access delay per questions; REQUIRE t_uart_mon bringup done with divisor ACKed and DLAB equals 0 and uart_serial_data monitor emitting TX plus RX byte transactions or TEST_TIMEOUT_CYCLES expiry as operational limit [f_dlab_gate]
2. BINDINGS_AND_OWNERSHIP: wishbone_slave_interface owns wb_adr_i 3BIT pin values plus wb_dat_i plus wb_we_i plus wb_stb_i plus wb_cyc_i plus wb_sel_i and observes wb_dat_o plus wb_ack_o; uart_serial_data drives srx_pad_i and observes srx_pad_i plus stx_pad_o; interrupt_output observes int_o; modem_control_if owns cts_pad_i plus dsr_pad_i plus ri_pad_i plus dcd_pad_i and owns rts_pad_o plus dtr_pad_o; wb_clk_i is common clock and wb_rst_i is common reset; write read addresses are pin values 0 for THR_RBR and 5 for LSR with DLAB equals 0 [f_lsr_addr,f_thr_input,f_rbr_output,f_dlab_gate]
3. CONFIG_AGREEMENT: REQUIRE LCR bus programming equals uart_serial_data SYM_DATA_BITS plus SYM_PARITY plus SYM_STOP and divisor derived SYM_BIT_CYCLES; KEEP bus idle owned by wishbone_slave_interface and srx_pad_i idle owned by uart_serial_data without assuming inactive levels; LSR reset is null and no mirror is used for side effect status [f_lsr_clear]

## Stimulus pseudocode

```text
1. STAGE0_BRINGUP: wishbone_slave_interface drives divisor latch writes at pin values 0 and 1 with DLAB equals 1 then drives LCR write to clear DLAB to 0 and to set SYM_LINE_FORMAT; WAIT for wb_ack_o per write; virtual sequence spawns per agent sequences only with no VIFs and no delays [f_dlab_gate]
2. STAGE1_BASIC: FOR one payload byte DO wishbone_slave_interface drives THR write at pin value 0 then uart_serial_data drives RX frame with no error using SYM settings then wishbone_slave_interface drives LSR read at pin value 5 then RBR read at pin value 0; WAIT for drain_cycles between transfers as operational limit [f_thr_input,f_rbr_output,f_dr]
3. STAGE2_ERROR_CROSS: FOR each ERR in OE PE FE BI DO IF ERR equals OE THEN uart_serial_data drives back to back RX frames to fill FIFO plus one extra shift char ELSE IF ERR equals PE THEN drives RX frame with inverted parity ELSE IF ERR equals FE THEN drives RX frame with missing stop ELSE drives srx_pad_i held at 0 for one char time of start plus data plus parity plus stop; CONCURRENTLY wishbone_slave_interface drives THR writes and RBR reads and LSR reads at pin values 0 and 5 to capture concurrent error status [f_oe_cond,f_pe_cond,f_fe_cond,f_bi_cond,f_bi_zero]
4. STAGE3_RANDOM: FOR N iterations DO wishbone_slave_interface drives constrained random THR writes plus LSR reads plus RBR reads filtered to pin values 0 and 5 with DLAB equals 0 and uart_serial_data drives constrained random RX frames with random ERR injection using agreed SYM settings; EXCLUDE divisor and config writes from payload; virtual sequence spawns only [f_dr,f_oe_cond,f_pe_cond,f_fe_cond,f_bi_cond]
5. CLEANUP: wishbone_slave_interface drives DLAB equals 0 and releases bus to idle; uart_serial_data releases srx_pad_i to idle owned level; WAIT for drain_cycles then TERMINATE or on TEST_TIMEOUT_CYCLES expiry TERMINATE [f_dlab_gate]
```

## Check pseudocode

```text
1. CHECK_LSR_STATUS: COMPARE observed completed LSR read data at pin value 5 DR OE PE FE BI bits against injected RX condition where DR 1 means data present and OE means FIFO full plus extra char and PE means top char parity error and FE means top char no valid stop and BI means break with zero char; COMPARE second LSR read to expect cleared bits upon reading [f_dr,f_oe_cond,f_pe_cond,f_fe_cond,f_bi_cond,f_bi_zero,f_lsr_clear]
2. CHECK_RLS_INT_AND_ROUTE: WAIT for int_o via interrupt_output then COMPARE Receiver Line Status source versus LSR error with reset by LSR read; COMPARE queue of observed completed RBR reads at pin value 0 versus queue of uart RX drives and queue of observed serial TX on stx_pad_o versus queue of THR writes at pin value 0 filtered by origin and address excluding config writes with TX as DUT output and RX as DUT input and never comparing an event with itself [f_rls_src,f_rls_reset,f_thr_input,f_rbr_output,f_tx_clear,f_err_summary]
```

## Coverage pseudocode

```text
1. COVER_LSR: SAMPLE cg_lsr_status on each LSR read completion via wishbone_slave_interface monitor analysis port with coverpoints cp_lsr_dr plus cp_lsr_oe plus cp_lsr_pe plus cp_lsr_fe plus cp_lsr_bi using bins dr_0_empty dr_1_data oe_0_no oe_1_overrun pe_0_no pe_1_parity fe_0_no fe_1_framing bi_0_no bi_1_break with per instance false [f_dr,f_oe_cond,f_pe_cond,f_fe_cond,f_bi_cond]
2. COVER_CROSS: SAMPLE cg_cross_transfer_error on each THR write at pin value 0 or RBR read at pin value 0 with concurrent LSR error status via combined wishbone_slave_interface plus uart_serial_data monitor analysis ports using bins thr_write_X_no_error thr_write_X_oe thr_write_X_pe thr_write_X_fe thr_write_X_bi rbr_read_X_no_error rbr_read_X_oe rbr_read_X_pe rbr_read_X_fe rbr_read_X_bi and ignore_bins idle_no_transfer with per instance false [f_thr_input,f_rbr_output,f_rls_src,f_err_summary]
3. COVER_INFRA: USE dedicated coverage subscribers tapping monitor analysis ports for sampling with drivers never supplying actual results or coverage events and with every assertion receiving property plus activation covers [f_lsr_clear,f_rls_reset]
```

## Completion

1. DONE when cg_lsr_status has hit both values for DR OE PE FE BI and cg_cross_transfer_error has hit THR plus RBR crossed with no_error OE PE FE BI or TEST_TIMEOUT_CYCLES expires as testbench operational limit
2. BOUND by TEST_TIMEOUT_CYCLES plus drain_cycles plus request_timeout_cycles as testbench operational limits not DUT timing; ON common reset WAIT then DISCARD partial serial frames in uart_serial_data monitor and REALIGN to next start bit
3. CLEANUP leaves DLAB equals 0 with wishbone bus idle owned by wishbone_slave_interface and srx_pad_i idle owned by uart_serial_data [f_dlab_gate]

## Questions

1. What is wb_rst_i polarity and required deassert to first wishbone access delay?
2. What is exact divisor to bit timing including divisor times 16 relation plus SYM_BIT_CYCLES value and mid bit sampling offset for monitor reconstruction?
3. What are idle plus start plus stop levels on srx_pad_i and stx_pad_o and owned idle level for srx_pad_i and modem inputs cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i?
4. What are legal wb_sel_i values under DATA_BUS_WIDTH_8 with 8BIT data and 3BIT wb_adr_i pin representation for addresses 0 and 5?
5. What is RX FIFO depth plus FCR trigger plus IER enable programming needed to deterministically cause OE and observe Receiver Line Status interrupt without loss?
6. What is LSR reset value which is undocumented and must remain null plus effect of Transmit empty and error summary bits 5 to 7 on this coverage?
7. What is exact Even Parity select generation versus checking rule for odd versus even number of 1s including stick parity interaction for transmit versus receive?
8. What defines concurrent LSR error sampling window for THR write or RBR read cross including same clock versus read after write ordering?

## Essential blockers


## Specification evidence

- `f_lsr_addr` → `/registers/registers/9` / `CH-f88915355b`
> Line Status 5 8 R Status information

- `f_thr_input` → `/sections/9/entries/6` / `CH-f88915355b`
> Transmit FIFO input

- `f_rbr_output` → `/sections/9/entries/6` / `CH-f88915355b`
> Receiver FIFO output

- `f_dlab_gate` → `/sections/9/entries/6` / `CH-f88915355b`
> At this time the above registers at addresses 0-1 can’t be accessed.

- `f_dr` → `/sections/9/entries/3` / `CH-a2dd758e55`
> No characters in the FIFO

- `f_oe_cond` → `/registers/registers/9/fields/1` / `CH-a2dd758e55`
> If the FIFO is full and another character has been

- `f_pe_cond` → `/registers/registers/9/fields/2` / `CH-a2dd758e55`
> The character that is currently at the top of the FIFO

- `f_fe_cond` → `/registers/registers/9/fields/3` / `CH-a2dd758e55`
> The received character at the top of the FIFO did not

- `f_bi_cond` → `/sections/9/entries/3` / `CH-a2dd758e55`
> The break occurs when the line is held in logic 0 for a

- `f_bi_zero` → `/sections/9/entries/3` / `CH-a2dd758e55`
> one zero character enters the FIFO and the UART waits for a

- `f_lsr_clear` → `/sections/8/entries/6` / `CH-a2dd758e55`
> The bit is cleared upon reading from the register.

- `f_rls_src` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Parity, Overrun or Framing
> errors or Break Interrupt

- `f_rls_reset` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Reading the Line
> Status Register

- `f_tx_clear` → `/sections/8/entries/7` / `CH-4e1d3a956c`
> The bit is cleared when data is being been written to the
> transmitter FIFO.

- `f_err_summary` → `/sections/8/entries/7` / `CH-4e1d3a956c`
> At least one parity error, framing error or break
