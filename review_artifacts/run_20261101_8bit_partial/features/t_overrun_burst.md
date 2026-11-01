# Overrun corner burst

Work package: `t_overrun_burst` · traffic · NEEDS_REVIEW

## Dependent features

- `t_loopback_stage`: Overrun burst reuses staged THR to Receiver Buffer transfer sequences with varied pop timing.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_obs_mon`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_shared_dir`, `t_traffic_err`, `t_wb_acc_cov`, `t_wb_mon`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Overrun corner burst reuses t_loopback_stage staged transfer setup to fill Receiver FIFO via serial_data RX bursts then inject extra characters while full with varied Receiver Buffer pop timing, checking DOCUMENTED LSR bit1 OE reporting, FIFO-intact DR, clear-on-LSR-read and Receiver Line Status IIR 011 with pending bit; burst_depth and pop timing are symbolic INFERRED knobs, all expectations from DOCUMENTED LSR-IIR-FCR items.

## Preconditions

1. PRE clock running at symbolic fixed period via common clock and reset released via common reset with symbolic polarity; wishbone_bus owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i and observes wb_dat_o wb_ack_o, serial_data owns srx_pad_i and observes stx_pad_o, modem_control_if owns cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i at symbolic idle, uart_interrupt observes int_o
2. PRE Receiver FIFO cleared via documented FCR bit1 write-then LSR read shows OE cleared and DR 0 empty before burst [f_rx_fifo_clear] [f_overrun_field] [f_dr_field]
3. PRE serial frame and divisor use symbolic programming agreed between configuration bus writes and serial_data driver-monitor bit_cycles; symbolic knob burst_depth scales fill level and symbolic full-heavy distribution varies pop timing as architecture only, no invented depth or timing values

## Stimulus pseudocode

```text
1. STAGE 0 directed bring-up: virtual spawns only, no VIFs or delays; wishbone_bus child clears FIFO then polls LSR for DR 0 and OE 0, serial_data child sends one clean RX character then wishbone_bus child pops Receiver Buffer and polls LSR [f_rx_fifo_clear] [f_dr_field]
2. STAGE 1 fill burst: virtual concurrently spawns serial_data burst of symbolic burst_depth RX characters back-to-back at symbolic divisor-derived character time with no pops to hold full, plus wishbone_bus LSR polls for DR 1 to flag FIFO-full event; per-agent children drive only own interface
3. STAGE 2 overrun injection with varied pop timing: FOR each corner iteration IF FIFO-full event THEN serial_data injects extra RX character while full including back-to-back overrun events WHILE wishbone_bus varies Receiver Buffer pop timing over no-pop versus immediate-pop versus delayed-pop symbolic schedule; track RX versus Receiver Buffer read completed-transaction queues filtered by origin, configuration writes excluded
4. STAGE 3 recovery: wishbone_bus LSR read to clear OE then drain remaining FIFO via Receiver Buffer reads, plus serial_data clean traffic to show return to OE 0 with DR progression [f_overrun_field]
```

## Check pseudocode

```text
1. COMPARE LSR bit1 OE equals 1 after FIFO-full plus extra character received in shift register via wishbone_bus LSR read completion queue [f_overrun_field] [f_overrun_required]
2. COMPARE FIFO-intact after overrun: LSR bit0 DR remains 1 and prior FIFO occupancy still readable via Receiver Buffer read completions without loss, configuration writes excluded from payload route [f_dr_field] [f_dr_required]
3. COMPARE LSR OE clears upon LSR read: second LSR read shows bit1 equals 0 while DR reflects remaining occupancy [f_overrun_field]
4. COMPARE IIR bits 3-1 equals 011 Receiver Line Status with bit0 equals 0 pending when OE set, reset by Reading LSR, with int_o observed via uart_interrupt plus wishbone_bus IIR read [f_iir_rls] [f_iir_pending] [f_iir_check]
```

## Coverage pseudocode

```text
1. SAMPLE monitor-sampled LSR OE equals 1 with DR equals 1 in FIFO-full overrun window via dedicated subscriber tapping wishbone_bus monitor LSR-read analysis port and serial_data monitor rx analysis port [f_overrun_required] [f_dr_required]
2. SAMPLE varied pop-timing strata: no-pop versus pop-during-overrun versus back-to-back overrun with IIR 011 Receiver Line Status activation [f_iir_rls] [f_iir_check]
3. SAMPLE LSR read-clear transition OE 1 to 0 and interrupt pending 0 to 1 as activation covers for OE checks [f_overrun_field] [f_iir_pending]
```

## Completion

1. WAIT all spawned wishbone_bus plus serial_data children complete OR UNTIL TESTBENCH request_timeout_cycles expires as operational limit only, not DUT timing
2. DRAIN wishbone_bus plus serial_data plus uart_interrupt monitors for drain_cycles as TESTBENCH operational limit then close virtual sequence
3. CLEANUP deassert wb_stb_i and wb_cyc_i via wishbone_bus driver to symbolic idle, release sequencer handles, leave serial_data and modem_control_if at symbolic idle, re-clear Receiver FIFO via documented FCR action if needed [f_rx_fifo_clear]

## Questions

1. What is DOCUMENTED Receiver FIFO depth and full threshold in bytes and exact overrun arrival timing: shift-register-complete while full versus start-of-next-character overwrite, beyond already DOCUMENTED FIFO-intact and clear-on-LSR-read semantics?
2. What are DOCUMENTED WISHBONE bindings for Receiver Buffer pop read, LSR read and IIR read in DATA_BUS_WIDTH_8 build: literal wb_adr_i pin values, DLAB gating for divisor versus data addresses, access types, and legality of unused addresses?
3. What are DOCUMENTED legal serial frame and divisor programming for overrun bursts: LCR data_bits parity stop_bits, divisor latch values, divisor-derived character time and fixed wb_clk_i period for bit_cycles agreement between bus writes and serial_data driver-monitor?
4. What is active level of wb_rst_i, inactive idle levels of wb_stb_i wb_cyc_i wb_we_i wb_sel_i srx_pad_i cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i, owners or tie_offs for all DUT inputs during burst, wb_ack_o latency and back-to-back idle rule, and TESTBENCH request_timeout_cycles plus drain_cycles values?
5. What are DOCUMENTED comparison masks and read-clear mirror handling for LSR OE versus DR and IIR RLS code when checking FIFO-intact and OE 1-to-0 on LSR read, with configuration writes excluded from payload routes?

## Essential blockers


## Specification evidence

- `f_overrun_field` → `/registers/registers/9/fields/1` / `CH-a2dd758e55`
>  ‘1’ – If the FIFO is full and another character has been
> received in the receiver shift register. If another character is starting
> to arrive, it will overwrite the data in the shift register but the FIFO
> will remain intact. The bit is cleared upon reading from the register.
> Generates Receiver Line Status interrupt.

- `f_overrun_required` → `/sections/8/entries/9` / `CH-a2dd758e55`
> If the FIFO is full and another character has been
> received in the receiver shift register.

- `f_dr_field` → `/registers/registers/9/fields/0` / `CH-a2dd758e55`
>  ‘0’ – No characters in the FIFO
>  ‘1’ – At least one character has been received and is in the
> FIFO.

- `f_dr_required` → `/sections/8/entries/8` / `CH-a2dd758e55`
> At least one character has been received and is in the
> FIFO.

- `f_iir_rls` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 1 1 1 st Receiver Line
> Status
> Parity, Overrun or Framing
> errors or Break Interrupt
> Reading the Line
> Status Register

- `f_iir_check` → `/sections/8/entries/6` / `CH-f91cbf1c05`
> Parity, Overrun or Framing
> errors or Break Interrupt
> Reading the Line
> Status Register

- `f_iir_pending` → `/sections/8/entries/5` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’. When it’s ‘1’ – no interrupt
> is pending.

- `f_rx_fifo_clear` → `/registers/registers/5/fields/1` / `CH-dfb1048908`
> Writing a ‘1’ to bit 1 clears the Receiver FIFO and resets its logic.
> But it doesn’t clear the shift register, i.e. receiving of the current
> character continues.
