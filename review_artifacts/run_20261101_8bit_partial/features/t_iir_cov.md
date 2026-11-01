# Interrupt identification coverage

Work package: `t_iir_cov` · coverage · NEEDS_REVIEW

## Dependent features

- `t_obs_mon`: Interrupt pending and priority coverage requires passive interrupt observer transactions.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_uart_cfg`, `t_wb_acc_cov`, `t_wb_mon`, `t_wb_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Cover IIR pending bit0 and highest-priority bits 3-1 codes with documented source-reset controls plus fixed bits 7-6 on every wishbone_bus IIR read using passive uart_interrupt observation.

## Preconditions

1. Clock running on wb_clk_i and reset on wb_rst_i with symbolic polarity-duration-sequencing pending question; IIR at reset C1h [f_iir_reset]
2. Bindings: wishbone_bus owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i and observes wb_dat_o wb_ack_o; uart_interrupt observes int_o; serial_data owns srx_pad_i and observes stx_pad_o; modem_control_if owns cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and observes rts_pad_o dtr_pad_o; clock owns wb_clk_i and reset owns wb_rst_i
3. IIR read is wishbone_bus READ with 3-bit wb_adr_i value 2 and read-only access [f_iir_reg]
4. Passive observers from t_obs_mon available for wishbone_bus IIR reads and uart_interrupt events

## Stimulus pseudocode

```text
1. wishbone_bus: READ address 2 after reset to capture no-pending baseline [f_iir_nopending1 f_iir_reset]
2. FOR each documented source IN line-status rx-available timeout THRE-empty modem-status DO: owner creates source via serial_data or modem_control_if or wishbone_bus documented reset-control complement THEN wishbone_bus READs IIR address 2 [f_iir_code011 f_iir_code010 f_iir_code110 f_iir_code001 f_iir_code000]
3. wishbone_bus: APPLY documented reset controls read LSR, drop FIFO below trigger, read Receiver Buffer, write THR or read IIR, read MSR each on owning interface only [f_iir_reset_line f_iir_rx_trig f_iir_timeout_reset f_iir_thre_reset f_iir_modem_reset]
4. wishbone_bus: RE-READ IIR address 2 after each reset control to observe pending clear or next highest priority [f_iir_highest f_iir_pending0]
```

## Check pseudocode

```text
1. COMPARE IIR bit0 pending 0 versus no-pending 1 from wishbone_bus IIR read data against uart_interrupt observation [f_iir_pending0 f_iir_nopending1]
2. COMPARE IIR bits 3-1 highest-priority code 011 010 110 001 000 against active documented source present before read [f_iir_highest f_iir_code011 f_iir_code010 f_iir_code110 f_iir_code001 f_iir_code000]
3. COMPARE IIR source-reset pairing: line-status source with LSR read reset, RX-available with FIFO-below-trigger reset, timeout with Receiver-Buffer read reset, THRE-empty with THR-write-or-IIR-read reset, modem with MSR-read reset [f_iir_src_line f_iir_reset_line f_iir_rx_trig f_iir_timeout_src f_iir_thre_reset f_iir_modem_reset f_iir_timeout_reset]
4. COMPARE IIR bits 7-6 equal 1 on every IIR read [f_iir_fixed76]
```

## Coverage pseudocode

```text
1. SAMPLE navigation label cg_iir_basic pending bin and code bins from wishbone_bus monitor IIR read data valid at clock edge [f_iir_pending0 f_iir_nopending1 f_iir_code011 f_iir_code010 f_iir_code110 f_iir_code001 f_iir_code000]
2. SAMPLE fixed compatibility bits 7-6 equals 1 on every sampled IIR read [f_iir_fixed76]
3. SAMPLE reset-control association observed with each IIR code sample for later cross analysis [f_iir_reset_line f_iir_rx_trig f_iir_timeout_reset f_iir_thre_reset f_iir_modem_reset]
```

## Completion

1. WAIT for wishbone_bus IIR read queue and uart_interrupt event queue to drain within TEST_TIMEOUT_CYCLES operational limit not DUT timing
2. CLEANUP release wishbone_bus serial_data modem_control_if uart_interrupt handles with monitors driving nothing

## Questions

1. Confirm IIR types and fixed-bits property activation including sampling clock edge, reset disable, and read-valid definition for every IIR read?
2. Confirm IIR bits 5-4 fixed value reset and sampling given excerpt states Bits 4 and 5 Logic 0 but no DOCUMENTED field item?
3. How does each IER enable bit gate IIR reporting and int_o assertion priority and clearing including which wishbone_bus access clears each RDA THRE line-status modem-status source?
4. Confirm wb_rst_i polarity duration sequencing, wb_clk_i period, wb_adr_i representation, and wb_sel_i wb_stb_i wb_cyc_i wb_ack_o handshake including inactive levels for coverage sampling?
5. How are undocumented IIR codes 100 101 111 to be handled for illegal-bin coverage?
6. How is 4-char-time timeout defined versus divisor and char format and what FIFO trigger level creates Receiver Data available for directed stimulus?
7. How is highest priority resolved when multiple sources pending simultaneously including THRE clearing by THR write versus IIR read and modem delta mapping?

## Essential blockers


## Specification evidence

- `f_iir_reg` → `/registers/registers/6` / `CH-f88915355b`
> Interrupt Identification 2 8 R Get interrupt information

- `f_iir_reset` → `/registers/registers/6` / `CH-f91cbf1c05`
> Reset Value: C1h

- `f_iir_pending0` → `/registers/registers/6/fields/0` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’.

- `f_iir_nopending1` → `/registers/registers/6/fields/0` / `CH-f91cbf1c05`
> When it’s ‘1’ – no interrupt
> is pending.

- `f_iir_highest` → `/sections/8/entries/6` / `CH-f91cbf1c05`
> The IIR enables the programmer to retrieve what is the current highest priority pending
> interrupt.

- `f_iir_code011` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 1 1 1 st Receiver Line

- `f_iir_code010` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 1 0 2 nd Receiver Data

- `f_iir_code110` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 1 1 0 2 nd Timeout

- `f_iir_code001` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 0 1 3 rd Transmitter

- `f_iir_code000` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 0 0 4 th Modem Status CTS, DSR, RI or DCD. Reading the Modem

- `f_iir_src_line` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Parity, Overrun or Framing

- `f_iir_reset_line` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Reading the Line
> Status Register

- `f_iir_rx_trig` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> FIFO trigger level reached FIFO drops below
> trigger level

- `f_iir_timeout_src` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> There’s at least 1 character
> in the FIFO but no character
> has been input to the FIFO
> or read from it for the last 4
> Char times.

- `f_iir_timeout_reset` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Reading from the
> FIFO (Receiver
> Buffer Register)

- `f_iir_thre_reset` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Writing to the
> Transmitter Holding
> Register or reading
> IIR.

- `f_iir_modem_reset` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Reading the Modem
> status register.

- `f_iir_fixed76` → `/registers/registers/6/fields/3` / `CH-f91cbf1c05`
> Bits 6 and 7: Logic ‘1’ for compatibility reason.
