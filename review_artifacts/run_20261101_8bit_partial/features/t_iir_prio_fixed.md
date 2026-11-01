# IIR priority and fixed bits

Work package: `t_iir_prio_fixed` · check · NEEDS_REVIEW

## Dependent features

- `t_ier_iir_en`: IIR highest-priority reporting and fixed bits check requires enabled interrupt sources settled first.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_reset`, `t_iir_cov`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_wb_acc_cov`, `t_wb_mon`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Verify IIR bits 3-1 report highest priority pending interrupt with documented source and reset control and bit0 pending indication, and every IIR read returns bits 7-6 as 1 and bits 5-4 as 0, after t_ier_iir_en settles enables; fixed-bits assertion and cover are quick-test temporary inferred checks backed by documented field definitions.

## Preconditions

1. Dependency t_ier_iir_en settled: IER enables programmed via wishbone_bus with normal registers accessed and sources idle before IIR priority checks
2. DUT in DATA_BUS_WIDTH_8 FIFO-only compatible build with UART_ADDR_WIDTH 3 and UART_DATA_WIDTH 8; use symbolic IIR address from documented address 2 without assuming literal wb_adr_i encoding
3. Apply the clock and reset with symbolic polarity; expect IIR reset value C1h after reset
4. wishbone_bus owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i and observes wb_dat_o wb_ack_o; uart_interrupt uses custom monitor to observe int_o with symbolic polarity; serial_data and modem_control_if own stimulus inputs with symbolic idle tie_offs
5. Serial data_bits parity stop_bits bit_cycles track LCR programming symbolically; wishbone_bus configuration writes agree with serial_data driver and monitor settings

## Stimulus pseudocode

```text
1. STAGE bringup: SPAWN wishbone_bus IIR read sequence to SAMPLE reset value and fixed bits; WAIT for read completion
2. STAGE line_status: SPAWN serial_data error-frame stimulus to create Receiver Line Status; SPAWN wishbone_bus IIR polls to SAMPLE 011; SPAWN wishbone_bus LSR read for reset control
3. STAGE rx_available_timeout: SPAWN serial_data burst and idle gap to create 010 and 110; SPAWN wishbone_bus IIR polls plus RBR reads to SAMPLE codes and exercise FIFO-below-trigger and RBR-read resets
4. STAGE thre_modem: SPAWN wishbone_bus THR write plus IIR poll to create and SAMPLE 001; SPAWN modem_control_if delta stimulus plus wishbone_bus MSR read to create and SAMPLE 000
5. STAGE priority_overlap: SPAWN combined serial_data plus modem_control_if plus THR-empty sources; SPAWN wishbone_bus IIR polls to SAMPLE highest-priority code with 011 over 010 and 110 over 001 over 000
6. STAGE fixed_bits_soak: SPAWN wishbone_bus back-to-back IIR reads across all stages to SAMPLE bits 7-6 and 5-4 on every read
```

## Check pseudocode

```text
1. COMPARE observed IIR bits 3-1 against active source set: EXPECT 011 line-status, 010 data-available, 110 timeout, 001 THRE-empty, 000 modem-status with highest priority winning
2. COMPARE IIR bit0: EXPECT 0 when any source pending else 1 consistent with int_o observed via uart_interrupt custom monitor
3. COMPARE every IIR read data: EXPECT bits 7-6 equal 1 and bits 5-4 equal 0
4. COMPARE reset controls via follow-up IIR poll: EXPECT LSR read clears 011, FIFO below trigger clears 010, RBR read clears 110, THR write or IIR read clears 001, MSR read clears 000
5. COMPARE post-reset IIR: EXPECT C1h with fixed bits intact and no-pending indication
```

## Coverage pseudocode

```text
1. SAMPLE pending and code via dedicated subscriber tapping wishbone_bus IIR read monitor: pending versus no-pending, 000 modem-status, 001 THRE-empty, 010 rx-data, 110 timeout, 011 line-status
2. SAMPLE fixed compatibility bits on every IIR read via dedicated subscriber tapping wishbone_bus monitor; drivers never supply coverage events
3. SAMPLE reset-control correlations: read LSR, FIFO below trigger, read RBR, write THR or read IIR, read MSR versus IIR code change
```

## Completion

1. WAIT all spawned wishbone_bus serial_data modem_control_if children complete OR UNTIL TESTBENCH request_timeout_cycles expires as operational limit only, not DUT timing
2. DRAIN wishbone_bus and uart_interrupt monitors for drain_cycles as TESTBENCH operational limit then close virtual sequence
3. CLEANUP return wishbone_bus to idle via driver, release sequencer handles, leave serial_data and modem_control_if idle; virtual sequence spawns only, no VIFs or delays

## Questions

1. What is wb_rst_i active level and sampling clock edge for IIR reads and int_o observation?
2. What are wb_stb_i wb_cyc_i wb_we_i inactive levels, wb_sel_i legal value for 8-bit data, wb_adr_i literal pin encoding for IIR address 2, and wb_ack_o latency?
3. What is int_o assertion polarity and clearing behavior, and does disabled IER source still affect IIR bit0 and bits 3-1 or only int_o?
4. Who drives srx_pad_i cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and observes stx_pad_o rts_pad_o dtr_pad_o int_o during this feature, and what are idle tie_offs?
5. How must serial_data data_bits parity stop_bits bit_cycles track LCR programming and agree with wishbone_bus config writes for line-status, data-available and timeout stimulus?
6. What are comparison masks for IIR bits 7-4 and handling of side-effect IIR read that clears THRE and DLAB banking for IIR access?
7. What are TESTBENCH request_timeout_cycles drain_cycles and back-to-back idle rule for IIR reads and LSR RBR THR MSR reset accesses?

## Essential blockers


## Specification evidence

- `f_iir_func` → `/sections/8/entries/6` / `CH-f91cbf1c05`
> The IIR enables the programmer to retrieve what is the current highest priority pending

- `f_iir_addr` → `/registers/registers/6` / `CH-f88915355b`
> Interrupt Identification 2 8 R Get interrupt information

- `f_iir_reset` → `/registers/registers/6` / `CH-f91cbf1c05`
> Reset Value: C1h

- `f_iir_b0_pend` → `/registers/registers/6/fields/0` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’.

- `f_iir_b0_idle` → `/registers/registers/6/fields/0` / `CH-f91cbf1c05`
> When it’s ‘1’ – no interrupt

- `f_iir_011` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 1 1 1 st Receiver Line

- `f_iir_010` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 1 0 2 nd Receiver Data

- `f_iir_110` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 1 1 0 2 nd Timeout

- `f_iir_001` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 0 1 3 rd Transmitter Holding

- `f_iir_000` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 0 0 4 th Modem Status CTS, DSR, RI or DCD.

- `f_iir_fix67` → `/registers/registers/6/fields/3` / `CH-f91cbf1c05`
> Bits 6 and 7: Logic ‘1’ for compatibility reason.

- `f_iir_fix45` → `/registers/registers/6/fields/2` / `CH-f91cbf1c05`
> Bits 4 and 5: Logic ‘0’.

- `f_iir_rst_lsr` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Reading the Line
> Status Register

- `f_iir_rst_rda` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> FIFO drops below

- `f_iir_rst_timeout` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Reading from the
> FIFO (Receiver
> Buffer Register)

- `f_iir_rst_thre` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Writing to the
> Transmitter Holding
> Register or reading
> IIR.

- `f_iir_rst_msr` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Reading the Modem
> status register.
