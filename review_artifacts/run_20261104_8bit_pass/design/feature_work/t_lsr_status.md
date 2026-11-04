# LSR status and clear

Work package: `t_lsr_status` · checks · NEEDS_REVIEW

## Dependent features

- `t_uart_mon`: LSR Data Ready and error status need TX RX byte reconstruction
- `t_wb_mon`: LSR read-clear and TX-empty clear need WISHBONE transactions

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_id_cov`, `t_line_err_cov`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Verify LSR DR reflects FIFO occupancy, OE/PE/FE/BI reflect FIFO-full plus top-character errors with RLS interrupt and clear on LSR read, TX empty cleared by transmitter FIFO writes, and error summary cleared on read, via WISHBONE LSR reads and serial rx/tx observation.

## Preconditions

1. Reset driven via reset with fixed-period clock; WAIT settle on clock; assume FIFOs cleared per f_init_fifo with unknown LSR reset as null
2. Ownership: wb_clk_i driven by clock, wb_rst_i driven by reset, wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i driven by wishbone_slave_interface, srx_pad_i driven by uart_serial_data, stx_pad_o wb_dat_o wb_ack_o int_o observed, modem inputs idle-owned by modem_control_if
3. Bus binding: LSR reads use actual pin value wb_adr_i=5 per f_lsr_addr with DLAB=0; THR/RBR pin values and wb_sel_i legal values remain symbolic pending source confirmation
4. Bring-up agrees between wishbone writes and uart_serial_data settings using symbolic divisor/LCR/FCR/IER values with RLS enable per f_ier_rls; concrete data_bits/parity/stop_bits/bit_cycles unresolved

## Stimulus pseudocode

```text
1. STAGE0 bring-up: wishbone_slave_interface programs divisor/LCR/FCR/IER to symbolic values with DLAB=0; uart_serial_data configures matching symbolic data_bits/parity/stop_bits/bit_cycles; WAIT idle
2. STAGE1 basic: wishbone_slave_interface SAMPLES LSR at 5 EXPECT TX empty 1 per f_txempty; wishbone_slave_interface writes THR symbolic payload THEN SAMPLES LSR EXPECT TX empty cleared; uart_serial_data drives one good rx byte THEN wishbone_slave_interface reads LSR EXPECT DR=1 per f_dr
3. STAGE2 errors: FOR each of parity/framing/break IN uart_serial_data drive one bad rx byte with matching attribute THEN wishbone_slave_interface reads LSR at 5; FOR overrun drive burst exceeding FIFO-full plus shift condition
4. STAGE3 summary: AFTER errors queued wishbone_slave_interface reads LSR EXPECT error summary 1 per f_errsum; AFTER LSR read WAIT THEN read LSR again to observe clear; virtual spawn only with no VIFs or delays
```

## Check pseudocode

```text
1. COMPARE LSR bit0 DR [f_dr] sampled on wishbone LSR read at pin 5 against uart_serial_data rx queue occupancy: DR=1 IF >=1 rx byte pending ELSE DR=0
2. COMPARE LSR OE/PE/FE/BI [f_oe,f_pe,f_fe,f_bi] sampled on LSR read against injected uart_serial_data rx attributes for top character: overrun IF FIFO-full plus shift char, parity-error IF top parity bad, framing-error IF top missing stop, break IF line held 0 for char time with zero char in FIFO
3. COMPARE clear-on-read [f_oe,f_pe,f_fe,f_bi,f_errsum]: IF LSR read completes THEN next LSR read shows OE/PE/FE/BI and error-summary cleared unless new error rx arrived before sample
4. COMPARE LSR transmit FIFO empty [f_txempty] and transmitter empty [f_txempty6]: SAMPLE LSR at 5 when idle EXPECT 1; AFTER wishbone THR write SAMPLE LSR EXPECT cleared to 0
5. COMPARE error summary [f_errsum]: IF any PE/FE/BI inside FIFO THEN bit7=1 ELSE 0; IF LSR read completes THEN next read shows 0 unless error still in FIFO
6. COMPARE interrupt_output int_o plus IIR 011 RLS [f_rls_reset,f_rls_prio] gated by IER bit2 [f_ier_rls]: IF OE/PE/FE/BI set AND IER RLS enabled THEN EXPECT RLS pending with reset on LSR read; IF TX empty set THEN EXPECT THRE with reset on THR write
```

## Coverage pseudocode

```text
1. SAMPLE cg_lsr_status DR/OE/PE/FE/BI bins [f_dr,f_oe,f_pe,f_fe,f_bi] via dedicated subscriber tapping wishbone_slave_interface monitor analysis port on each completed LSR read at pin 5
2. SAMPLE TX-empty and error-summary states [f_txempty,f_errsum] via same LSR-read subscriber; SAMPLE RLS 011 versus THRE signalling [f_rls_reset,f_rls_prio] via dedicated subscriber tapping interrupt_output monitor analysis port
3. SAMPLE rx error attributes versus tx activity via dedicated subscriber tapping uart_serial_data monitor analysis ports; drivers never supply coverage events
```

## Completion

1. Bound by TEST_TIMEOUT_CYCLES plus drain_cycles as TESTBENCH operational limits not DUT timing; on reset WAIT realign THEN discard partial serial frame and flush in-flight wishbone transfer
2. Done when basic DR plus TX-empty plus each of OE/PE/FE/BI and error-summary has at least one scoreboard COMPARE from LSR reads and at least one RLS interrupt COMPARE observed or TEST_TIMEOUT_CYCLES expires
3. Cleanup leaves DLAB=0 with wishbone bus idle-owned by wishbone_slave_interface and srx_pad_i idle-owned by uart_serial_data; modem inputs idle-owned by modem_control_if

## Questions

1. What are documented LSR bit numbers and reset values for DR versus TX FIFO empty versus transmitter empty versus error summary, and DR clear versus FIFO-occupancy tracking?
2. What is documented distinction for write-clear: LSR transmit empty/transmitter empty cleared by THR write versus IIR THRE reset by THR write or IIR read?
3. What are source-stated LCR data_bits/parity/stop_bits options and divisor-to-bit timing plus FCR trigger and IER bring-up values for serial error injection?
4. What is wb_rst_i polarity/duration, wb_adr_i pin values for THR/RBR/LSR/IER under DLAB=0, and wb_sel_i usage under DATA_BUS_WIDTH_8?
5. What is FIFO depth governing overrun full condition and does RBR pop advance top-character PE/FE/BI versus LSR read clear?
6. What is int_o signalling level/polarity for RLS versus THRE comparison when IER enables set?

## Essential blockers


## Specification evidence

- `f_dr` → `/sections/8/entries/6` / `CH-a2dd758e55`
>  ‘0’ – No characters in the FIFO
>  ‘1’ – At least one character has been received and is in the
> FIFO.

- `f_oe` → `/registers/registers/9/fields/1` / `CH-a2dd758e55`
>  ‘1’ – If the FIFO is full and another character has been
> received in the receiver shift register. If another character is starting
> to arrive, it will overwrite the data in the shift register but the FIFO
> will remain intact. The bit is cleared upon reading from the register.
> Generates Receiver Line Status interrupt.

- `f_pe` → `/registers/registers/9/fields/2` / `CH-a2dd758e55`
>  ‘1’ – The character that is currently at the top of the FIFO
> has been received with parity error. The bit is cleared upon reading
> from the register. Generates Receiver Line Status interrupt.

- `f_fe` → `/registers/registers/9/fields/3` / `CH-a2dd758e55`
>  ‘1’ – The received character at the top of the FIFO did not
> have a valid stop bit. Of course, generally, it might be that all the
> following data is corrupt. The bit is cleared upon reading from the
> register. Generates Receiver Line Status interrupt.

- `f_bi` → `/registers/registers/9/fields/4` / `CH-a2dd758e55`
> The break occurs when the line is held in logic 0 for a
> time of one character (start bit + data + parity + stop bit). In that
> case, one zero character enters the FIFO and the UART waits for a
> valid start bit to receive next character. The bit is cleared upon
> reading from the register. Generates Receiver Line Status interrupt.

- `f_txempty` → `/registers/registers/9/fields/5` / `CH-a2dd758e55`
>  ‘1’ – The transmitter FIFO is empty. Generates Transmitter
> Holding Register Empty interrupt. The bit is cleared when data is
> being been written to the transmitter FIFO.

- `f_txempty6` → `/sections/8/entries/7` / `CH-4e1d3a956c`
> are empty. The bit is cleared when data is being been written to the
> transmitter FIFO.

- `f_errsum` → `/sections/8/entries/7` / `CH-4e1d3a956c`
>  ‘1’ – At least one parity error, framing error or break
> indications have been received and are inside the FIFO. The bit is
> Bit # Access Description
> cleared upon reading from the register.

- `f_rls_reset` → `/sections/8/entries/4` / `CH-f91cbf1c05`
> Parity, Overrun or Framing
> errors or Break Interrupt
> Reading the Line
> Status Register

- `f_rls_prio` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 1 1 1 st Receiver Line
> Status

- `f_lsr_addr` → `/registers/registers/9` / `CH-f88915355b`
> Line Status 5 8 R Status information

- `f_ier_rls` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 2 RW Receiver Line Status Interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled

- `f_init_fifo` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> • The receiver and transmitter FIFOs are cleared.
