# IER enable and IIR pending

Work package: `t_ier_iir_en` · check · NEEDS_REVIEW

## Dependent features

- `t_uart_cfg`: IER gating of Received Data THRE Line Status Modem Status and IIR pending polarity require IER programming first.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_reset`, `t_iir_cov`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_wb_acc_cov`, `t_wb_mon`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Verify IER bits 0-3 gate Received Data THRE Line Status Modem Status generation and IIR bit0 reports 0 pending 1 no-pending after uart_cfg programs LCR divisor FIFO IER via wishbone_bus with DLAB 0, observing int_o via uart_interrupt and IIR via wishbone_bus while stimulating sources via serial_data and modem_control_if.

## Preconditions

1. WAIT clock stable and reset deasserted via common clock and reset, polarity TBD see questions; never name clock or reset agent
2. REQUIRE t_uart_cfg completed: LCR divisor FIFO programmed then IER programmable with DLAB 0 to access IER at wb_adr_i pin value 1 [f_ier_addr f_dlab_gate f_ier_prog]
3. BIND wishbone_bus to wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_sel_i wb_ack_o; uart_interrupt observes int_o RTL int_o for code spec INT_O for behavior; serial_data owns srx_pad_i and observes stx_pad_o; modem_control_if drives cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and observes rts_pad_o dtr_pad_o; bus addresses are literal wb_adr_i pin values
4. START from IER 00h all-disabled [f_ier_reset f_ier_disabled] and IIR C1h bit0 1 no-pending [f_iir_reset f_iir_pending]
5. USE symbolic serial data_bits parity stop_bits bit_cycles tracking uart_cfg LCR programming with config writes agreeing with serial driver monitor; masks tie-offs and timeout limits symbolic pending questions

## Stimulus pseudocode

```text
1. VIA wishbone_bus WRITE IER at wb_adr_i 1 with DLAB 0: FOR each directed combination in all-disabled 00h then single-bit 0 1 2 3 then multi-bit DO WRITE then READ back programming confirmation [f_ier_gate f_ier_bit0 f_ier_bit1 f_ier_bit2 f_ier_bit3 f_ier_prog f_ier_addr]
2. FOR each IER combination TRIGGER its source via owning agent only: serial_data RX frame for Received Data, wishbone_bus THR path for THRE, serial_data error frame for Line Status, modem_control_if delta for Modem Status; virtual sequence spawns per-agent children only no VIFs or delays
3. AFTER each trigger VIA wishbone_bus READ IIR at symbolic address and SAMPLE int_o via uart_interrupt monitor; WAIT settling under TESTBENCH operational limit only [f_iir_pending f_iir_highest]
4. REPEAT with all-disabled as first basic functional masking case then enabled cases; CLEAR via symbolic source-specific reads pending question; terminate on all combinations done
```

## Check pseudocode

```text
1. COMPARE int_o observed via uart_interrupt monitor against IER gated expectation: IF source active AND its IER bit f_ier_bit0 f_ier_bit1 f_ier_bit2 f_ier_bit3 is 1 THEN expect int_o asserted ELSE IF its IER bit is 0 THEN expect int_o not asserted for that source [f_ier_gate]
2. COMPARE IIR bit0 from wishbone_bus read data: IF any enabled source pending THEN expect 0 ELSE expect 1; use f_iir_pending polarity and f_iir_reset C1h equals 1 at reset; mask IIR bits 7-4 comparison TBD
3. COMPARE IER readback via wishbone_bus against written legal combinations with reserved 7-4 masked; START from 00h all-disabled [f_ier_reset f_ier_disabled]
```

## Coverage pseudocode

```text
1. SAMPLE via dedicated subscriber tapping wishbone_bus monitor on IIR read valid: cover IIR bit0 pending 0 versus no-pending 1 [f_iir_pending f_iir_reset]; drivers never supply coverage
2. SAMPLE via dedicated subscriber tapping wishbone_bus monitor on IER write: cover IER bits 0-3 combinations including all-disabled 00h and single-bit enables [f_ier_gate f_ier_disabled]
3. SAMPLE via dedicated subscriber tapping uart_interrupt monitor: cover int_o asserted versus deasserted per IER gating [f_ier_gate]
```

## Completion

1. WAIT all spawned wishbone_bus serial_data modem_control_if children complete OR UNTIL TESTBENCH request_timeout_cycles expires as operational limit only, not DUT timing
2. DRAIN wishbone_bus and uart_interrupt monitors for drain_cycles as TESTBENCH operational limit then close virtual sequence
3. CLEANUP return wishbone_bus to idle via driver, release sequencer handles, leave serial_data and modem_control_if idle; virtual sequence spawns only, no VIFs or delays

## Questions

1. Does IER 0 mask only int_o or also force IIR bit0 to 1, and which register access clears each source: RBR LSR MSR THR or IIR read?
2. What is INT_O assertion polarity level versus pulse priority and clearing when multiple IER enabled sources are pending?
3. What are wb_rst_i active level wb_stb_i wb_cyc_i wb_we_i inactive levels wb_sel_i legal with 8-bit data wb_adr_i literal pin representation IIR address confirmation addr 7 legality and wb_ack_o latency?
4. Who drives srx_pad_i cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and observes stx_pad_o rts_pad_o dtr_pad_o int_o during this feature, and what are tie_offs when idle?
5. How must serial_data data_bits parity stop_bits bit_cycles track LCR programming and agree with wishbone_bus config writes for each source stimulus?
6. What are comparison and mirror masks for IER reserved 7-4 and IIR bits 7-4 given IIR bits 6-7 1 and bits 4-5 0, and how are DLAB-banked IER versus divisor and side-effect IIR handled?
7. What are TESTBENCH request_timeout_cycles drain_cycles and back-to-back idle rule for IER writes and IIR reads?

## Essential blockers


## Specification evidence

- `f_ier_gate` → `/sections/8/entries/4` / `CH-de51b2eafc`
> This register allows enabling and disabling interrupt generation by the UART.

- `f_ier_bit0` → `/registers/registers/4/fields/0` / `CH-de51b2eafc`
> 0 RW Received Data available interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled

- `f_ier_bit1` → `/sections/8/entries/4` / `CH-de51b2eafc`
> 1 RW Transmitter Holding Register empty interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled

- `f_ier_bit2` → `/registers/registers/4/fields/2` / `CH-de51b2eafc`
> 2 RW Receiver Line Status Interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled

- `f_ier_bit3` → `/registers/registers/4/fields/3` / `CH-de51b2eafc`
> 3 RW Modem Status Interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled

- `f_ier_reset` → `/registers/registers/4` / `CH-de51b2eafc`
> Reset Value: 00h

- `f_ier_addr` → `/registers/registers/4` / `CH-f88915355b`
> Interrupt Enable 1 8 RW Enable/Mask interrupts

- `f_dlab_gate` → `/registers/registers/4` / `CH-f88915355b`
> At this time the above registers at addresses 0-1 can’t be accessed.

- `f_ier_disabled` → `/registers/registers/4` / `CH-1e2324cfc3`
> All interrupts are disabled in the Interrupt Enable Register.

- `f_ier_prog` → `/registers/registers/4` / `CH-1e2324cfc3`
> Enable desired interrupts by setting appropriate bits in the Interrupt Enable

- `f_iir_pending` → `/sections/8/entries/5` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’. When it’s ‘1’ – no interrupt

- `f_iir_highest` → `/sections/8/entries/6` / `CH-f91cbf1c05`
> The IIR enables the programmer to retrieve what is the current highest priority pending

- `f_iir_reset` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Reset Value: C1h
