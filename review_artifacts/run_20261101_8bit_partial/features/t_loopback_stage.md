# Loopback staged traffic

Work package: `t_loopback_stage` · traffic · NEEDS_REVIEW

## Dependent features

- `t_uart_cfg`: Staged THR to Receiver Buffer loopback transfers require LCR format divisor FIFO trigger and IER programming completed first.
- `t_wb_seq`: Loopback virtual sequences coordinate Wishbone THR accesses through shared virtual sequencer handle.
- `t_serial_seq`: Loopback virtual sequences coordinate serial SRX STX traffic through shared virtual sequencer handle.
- `t_modem_seq`: Loopback entry needs MCR loopback control and modem handshake coordination through shared virtual sequencer handle.

## Independent features

`t_clk_cov`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_lsr_par_fram`, `t_obs_mon`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_shared_dir`, `t_wb_acc_cov`, `t_wb_mon`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Loopback staged traffic coordinates wishbone_bus THR writes to Receiver Buffer reads via internal return under virtual sequencer with serial_data and modem_control_if handles after t_uart_cfg t_wb_seq t_serial_seq t_modem_seq. DOCUMENTED authority is limited to LSR DR occupancy and IIR priority; MCR loopback control, THR RBR addresses, LCR divisor FIFO IER values and payload equality remain INFERRED guidance only and are referenced symbolically without invented values.

## Preconditions

1. AFTER t_uart_cfg symbolic LCR divisor FIFO-trigger IER programming completed via wishbone_bus after clock and reset bring-up
2. AFTER t_wb_seq plus t_serial_seq plus t_modem_seq sequencer handles available on shared virtual sequencer for coordinated spawn
3. Clock running at selected fixed period and reset released with polarity symbolic pending answer
4. Agents bound with RTL names for code: wishbone_bus drives wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i observes wb_dat_o wb_ack_o; serial_data drives srx_pad_i observes stx_pad_o; modem_control_if drives cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i observes rts_pad_o dtr_pad_o; uart_interrupt observes int_o

## Stimulus pseudocode

```text
1. STAGE bringup: SPAWN virtual loopback_traffic on virtual sequencer with explicit handles to wishbone_bus plus serial_data plus modem_control_if; virtual spawns only, no VIFs or delays
2. FOR byte_index in 0 to SYM_loopback_count minus 1: SPAWN wishbone_bus write to SYM_THR with symbolic 8-bit payload; WAIT for write completion OR UNTIL TESTBENCH request_timeout_cycles expires
3. WAIT for Receiver Buffer arrival bounded by TESTBENCH timeout only; SPAWN wishbone_bus read of symbolic LSR then IF DR equals 1 SPAWN wishbone_bus read from SYM_RBR; FOR each transfer WAIT for completion
4. OBSERVE stx_pad_o via serial_data monitor and modem pins via modem_control_if monitor without asserting values; HOLD srx_pad_i at symbolic test-only idle via serial_data driver
```

## Check pseudocode

```text
1. COMPARE LSR bit0 observed via wishbone_bus monitor against Receiver Buffer occupancy: EXPECT 1 when at least one character queued ELSE 0 [f_lsr_dr_1,f_lsr_dr_0]
2. IF uart_interrupt observes int_o pending THEN COMPARE IIR bit0 pending indication and bits 3-1 highest-priority code with stated source and reset control [f_iir_pending_1,f_iir_code_1]
```

## Coverage pseudocode

```text
1. SAMPLE LSR DR occupancy from wishbone_bus monitor on THR or Receiver Buffer transfer: bins empty_0 versus queued_1
2. SAMPLE IIR pending and code from wishbone_bus monitor on IIR read: bins pending_0 versus idle_1 and modem_status versus thre_empty versus rx_data versus timeout versus line_status
```

## Completion

1. WAIT all spawned wishbone_bus children complete OR UNTIL TESTBENCH request_timeout_cycles expires as operational limit only
2. DRAIN wishbone_bus plus serial_data plus modem_control_if monitors for drain_cycles as TESTBENCH operational limit then close virtual sequence
3. CLEANUP deassert wb_stb_i and wb_cyc_i via wishbone_bus driver to symbolic idle, release explicit sequencer handles, leave serial_data and modem_control_if at symbolic idle

## Questions

1. Confirm loopback payload path and FIFO-only expectations for directed stage: DOCUMENTED authority for MCR loopback internal TX-to-RX return, STX level, DTR-to-DSR RTS-to-CTS Out1-to-RI Out2-to-DCD connections, and whether THR-write to Receiver-Buffer-read payload equality is DOCUMENTED or only LSR DR occupancy?
2. What are DOCUMENTED WISHBONE bindings for THR, Receiver Buffer, LSR, IIR, MCR: literal wb_adr_i pin values 0 to 6, DLAB gating for 0 to 1, access types, and legality of addr 7 in DATA_BUS_WIDTH_8 build?
3. What are DOCUMENTED legal LCR format, divisor, FIFO trigger and IER values and programming order including MSB-first LSB-next with DLAB set-then-clear for staged loopback traffic?
4. What is active level of wb_rst_i and inactive levels of wb_stb_i wb_cyc_i wb_we_i, legal wb_sel_i with 8-bit data, WB_ACK_O latency, back-to-back idle rule, and TESTBENCH request_timeout_cycles plus drain_cycles values?
5. What are owners or tie_offs and inactive idle levels for all DUT inputs during loopback: srx_pad_i cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i drivers and stx_pad_o rts_pad_o dtr_pad_o int_o observers, and serial bit_cycles tracking of LCR divisor?
6. What are DOCUMENTED comparison masks and mirror handling for THR Receiver Buffer LSR IIR given write-only and read-clear semantics, and can payload integrity exclude configuration writes and compare only completed write versus read queues?

## Essential blockers


## Specification evidence

- `f_lsr_dr_1` → `/sections/8/entries/8` / `CH-a2dd758e55`
>  ‘1’ – At least one character has been received and is in the
> FIFO.

- `f_lsr_dr_0` → `/sections/8/entries/8` / `CH-a2dd758e55`
>  ‘0’ – No characters in the FIFO

- `f_iir_pending_1` → `/sections/8/entries/6` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’. When it’s ‘1’ – no interrupt
> is pending.

- `f_iir_code_1` → `/sections/8/entries/6` / `CH-f91cbf1c05`
> 0 1 1 1 st Receiver Line
> Status
> Parity, Overrun or Framing
> errors or Break Interrupt
> Reading the Line
> Status Register
