# Modem by traffic cross

Work package: `t_modem_traffic_cov` · coverage · NEEDS_REVIEW

## Dependent features

- `t_modem_irq`: modem by traffic cross needs Modem Status interrupt base during data flow

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_reset_state`, `t_top_virtual`, `t_uart_mon`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Cover single-instance cross of Modem Status IIR 000 from CTS DSR RI DCD with concurrent serial traffic states idle tx_active rx_active tx_rx_active plus no_modem traffic sampled on IIR indication on clock edges during data flow

## Preconditions

1. Clock drives wb_clk_i and reset drives wb_rst_i to released state with symbolic polarity; wishbone_slave_interface owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i and uart_serial_data owns srx_pad_i and modem_control_if owns cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i [f_modem_pads_1]
2. LCR DLAB 0 for normal access with IER at address 1 and IIR at 2 and MSR at 6 accessible and divisor alias at 0-1 not selected [f_ier_addr_1] [f_iir_addr_1] [f_msr_addr_1] [f_dlab_gate_1]
3. IER bit3 Modem Status enabled to allow modem interrupt generation with serial link to external modem peer active [f_ier_ms_1] [f_serial_link_1]

## Stimulus pseudocode

```text
1. STAGE0_BRINGUP: wishbone_slave_interface writes SYM_IER with modem enable 1 and reads back; uart_serial_data holds idle; modem_control_if drives symbolic inactive; WAIT drain then SAMPLE IIR baseline [f_ier_ms_1] [f_iir_pending_1]
2. STAGE1_IDLE_MODEM: modem_control_if toggles one of CTS DSR RI DCD while uart_serial_data holds idle with no TX RX frames; wishbone_slave_interface observes IIR pending 0 and reads MSR to clear [f_modem_src_1] [f_iir_pending_1] [f_msr_addr_1]
3. STAGE2_TX_MODEM: uart_serial_data starts TX frames via THR path CONCURRENTLY with modem_control_if toggling modem input; wishbone_slave_interface observes IIR and MSR during TX active [f_serial_link_1] [f_modem_src_1]
4. STAGE3_RX_MODEM: uart_serial_data drives RX frames on srx_pad_i CONCURRENTLY with modem_control_if toggling modem input; wishbone_slave_interface observes IIR and MSR during RX active [f_serial_link_1] [f_modem_src_1]
5. STAGE4_TXRX_MODEM: uart_serial_data runs simultaneous TX and RX frames CONCURRENTLY with modem_control_if toggling modem input; wishbone_slave_interface observes IIR and MSR during combined activity [f_serial_link_1] [f_modem_src_1]
6. STAGE5_TRAFFIC_NOMODEM: uart_serial_data runs TX RX and TX_RX traffic with modem inputs held symbolic inactive and no MSR delta; wishbone_slave_interface observes IIR for no_modem_X_traffic [f_iir_pending_1]
7. FOR each modem source in CTS DSR RI DCD REPEAT STAGE1 through STAGE4 at least once; cleanup restores symbolic inactive and wishbone bus idle
```

## Check pseudocode

```text
1. COMPARE sampled IIR pending flag equals 0 when claiming modem_000 cross bin and equals 1 for idle no-interrupt baseline [f_iir_pending_1]
2. COMPARE sampled IIR fixed bits 6_7 equal 1 and bits 5_4 equal 0 when qualifying modem 000 indication [f_iir_fixed_1]
```

## Coverage pseudocode

```text
1. SAMPLE on CLK edges on Modem Status IIR indication via wishbone_slave_interface monitor plus concurrent tx_active rx_active flags via uart_serial_data monitor and modem_000 versus no_modem via modem_control_if monitor [f_iir_addr_1] [f_serial_link_1] [f_modem_pads_1] [f_modem_src_1]
2. COMPARE sampled tuple to bins modem_000_X_idle and modem_000_X_tx_active and modem_000_X_rx_active and modem_000_X_tx_rx_active and no_modem_X_traffic with per-instance false single UART
3. SAMPLE with dedicated subscriber tapping monitor analysis ports only; drivers never supply actual results or coverage events
```

## Completion

1. Done when bins modem_000_X_idle and modem_000_X_tx_active and modem_000_X_rx_active and modem_000_X_tx_rx_active and no_modem_X_traffic each hit at least once
2. Bound by TESTBENCH drain_cycles and request_timeout_cycles operational limits which are testbench limits not DUT timing
3. Cleanup returns wishbone_slave_interface to idle and srx_pad_i plus cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i to symbolic inactive for handoff

## Questions

1. What documented window defines tx_active versus rx_active versus idle concurrent with Modem Status IIR indication for sampling, including THR-write versus stx_pad_o versus srx_pad_i versus FIFO occupancy and cycle window?
2. What modem granularity defines modem_000 bin when multiple CTS DSR RI DCD deltas overlap or higher-priority RLS RDA Timeout THRE pending concurrently, and what defines no_modem_X_traffic versus no-pending versus other IIR code?
3. What serial data_bits parity stop_bits bit_cycles and divisor programming produce documented TX RX traffic for this cross?
4. What are wb_adr_i pin values for IER IIR MSR under DLAB 0, wb_sel_i handling, wb_rst_i polarity and release to first access delay, int_o polarity, and inactive drive levels for cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i plus srx_pad_i tie-off and wishbone idle ownership during concurrent traffic?
5. What MCR Loopback mode applies for normal external modem observation during data flow and are external modem inputs ignored in loopback?

## Essential blockers


## Specification evidence

- `f_modem_src_1` → `/sections/9/entries/7` / `CH-f91cbf1c05`
> 0 0 0 4 th Modem Status CTS, DSR, RI or DCD. Reading the Modem
> status register.

- `f_iir_pending_1` → `/sections/9/entries/2` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’. When it’s ‘1’ – no interrupt
> is pending.

- `f_iir_fixed_1` → `/sections/9/entries/2` / `CH-f91cbf1c05`
> Bits 4 and 5: Logic ‘0’.
> Bits 6 and 7: Logic ‘1’ for compatibility reason.

- `f_ier_ms_1` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 3 RW Modem Status Interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled

- `f_ier_addr_1` → `/sections/9/entries/5` / `CH-f88915355b`
> Interrupt Enable 1 8 RW Enable/Mask interrupts
> generated by the UART

- `f_iir_addr_1` → `/sections/9/entries/5` / `CH-f88915355b`
> Interrupt Identification 2 8 R Get interrupt information

- `f_msr_addr_1` → `/sections/9/entries/5` / `CH-f88915355b`
> Modem Status 6 8 R Modem Status

- `f_dlab_gate_1` → `/sections/9/entries/5` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set
> to ‘1’. At this time the above registers at addresses 0-1 can’t be accessed.

- `f_serial_link_1` → `/sections/4/strategy/overview/0` / `CH-2baa4497c0`
> The UART (Universal Asynchronous Receiver/Transmitter) core provides serial
> communication capabilities, which allow communication with modem or other external
> devices, like another computer using a serial cable and RS232 protocol.

- `f_modem_pads_1` → `/sections/4/strategy/agents/3` / `CH-d62a4ba2db`
> It requires 2 pads in the chip (serial in and serial out) and, optionally, another six modem
> control signals, which can otherwise be implemented using general purpose I/Os on the
> chip.
