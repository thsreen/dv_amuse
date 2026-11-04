# IER enable and IIR pending

Work package: `t_ier_iir_pend` · checks · NEEDS_REVIEW

## Dependent features

- `t_wb_top_seq`: IER IIR enable-pending check needs controlled register stimulus
- `t_irq_baud_mon`: pending comparison needs passive INT_O observation

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Verify IER bits 0-3 enable Received-Data THRE Receiver-Line-Status Modem-Status with 0 disabled 1 enabled via readback, and IIR bit0 0 pending 1 none correlated with passive int_o when enabled.

## Preconditions

1. Common reset driven then deasserted and observed on fixed-period clock; reset polarity and duration symbolic per q_reset [f_reset_disabled]
2. LCR DLAB==0 so addresses 0-1 access IER normal registers; IIR accessible [f_dlab_gate]
3. wishbone_slave_interface bound to wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i with symbolic IER_ADDR==1 and address representation per q_addr
4. interrupt_output bound to int_o passive observe only, timestamped on fixed clock; asserted versus negated levels symbolic per q_int_o

## Stimulus pseudocode

```text
1. INIT: APPLY common reset; READ IER at symbolic IER_ADDR via wishbone_slave_interface; READ IIR via wishbone_slave_interface; SAMPLE int_o via interrupt_output [f_ier_reset,f_iir_reset,f_reset_disabled]
2. ENSURE LCR DLAB==0 before any IER IIR access; if DLAB==1 THEN set DLAB==0 first [f_dlab_gate]
3. FOR each enable in 0x0 to 0xF with reserved 7-4==0: WRITE IER = enable via wishbone_slave_interface; READ IER back; READ IIR; SAMPLE int_o passively [f_ier_b0,f_ier_b1,f_ier_b2,f_ier_b3,f_ier_reserved]
4. IF dependency traffic creates documented source THEN WAIT for IIR bit0==0 pending else VERIFY IIR bit0==1 none; never drive int_o; per-agent drive only own interface [f_iir_pending]
5. CLEANUP: LEAVE DLAB==0 idle; WAIT drain_cycles flush; STOP on request_timeout_cycles operational limit
```

## Check pseudocode

```text
1. COMPARE IER readback [f_ier_b0,f_ier_b1,f_ier_b2,f_ier_b3,f_ier_reserved]: IF (read & 0x0F) != written_enables THEN FAIL; IF (read & 0xF0) != 0 THEN FAIL
2. COMPARE reset values: IER == 00h [f_ier_reset,f_reset_disabled]; IIR == C1h [f_iir_reset] so bit0==1 none-pending
3. COMPARE IIR fixed mask on every IIR read: bits7_6==11 AND bits5_4==00 [f_iir_zero,f_iir_one]
4. COMPARE pending correlation in top scoreboard: SAMPLE IIR bit0 plus int_o level together; IF IIR.bit0==1 THEN EXPECT no-pending with int_o at symbolic NEGATED level; IF IIR.bit0==0 AND corresponding IER bit==1 THEN EXPECT pending with int_o at symbolic ASSERTED level [f_iir_pending]; FAIL on mismatch where enable==1; polarity levels remain symbolic per q_int_o
5. COMPARE interrupt_output monitor queue vs wishbone IIR poll queue filtered by origin; exclude configuration writes; never compare event with itself
```

## Coverage pseudocode

```text
1. SAMPLE IER enable combinations 0000b-1111b seen on wishbone_slave_interface monitor; cover each bit 0/1 and all-combinations sweep
2. SAMPLE IIR bit0 pending 0 vs none 1 correlated with symbolic int_o level seen on interrupt_output subscriber
3. SAMPLE reset coverage: IER 00h and IIR C1h after common reset
4. SAMPLE IIR compatibility mask bits7_6==11 and bits5_4==00
```

## Completion

1. Done when reset entry plus all 16 IER enable combinations 0000b-1111b written/read via wishbone_slave_interface with at least one IER scoreboard comparison and at least one IIR-bit0 vs int_o scoreboard comparison observed
2. Bound by TEST_TIMEOUT_CYCLES plus drain_cycles flush as TESTBENCH operational limits, not DUT timing; stages execute in order, sequences within stage concurrent

## Questions

1. q_int_o: What is documented INT_O polarity and inactive level for correlating IIR bit0 0 pending versus 1 none with asserted versus negated INT_O?
2. q_reset: What is wb_rst_i active polarity, required reset duration in CLK cycles, and deassert-to-first-write delay for IER IIR checks?
3. q_addr: What is explicit wb_adr_i pin representation for IER address 1 and IIR reads and required handling of addr 7 illegal for 8-bit use?
4. q_bus_drive: What are required wb_sel_i values owners and tie-offs and inactive levels of wb_stb_i wb_cyc_i that must be driven for 8-bit FIFO-only register access?

## Essential blockers


## Specification evidence

- `f_ier_b0` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 0 RW Received Data available interrupt

- `f_ier_b1` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 1 RW Transmitter Holding Register empty interrupt

- `f_ier_b2` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 2 RW Receiver Line Status Interrupt

- `f_ier_b3` → `/registers/registers/4/fields/3` / `CH-de51b2eafc`
> 3 RW Modem Status Interrupt

- `f_ier_reserved` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 7-4 RW Reserved. Should be logic ‘0’.

- `f_ier_reset` → `/sections/8/entries/2` / `CH-de51b2eafc`
> Reset Value: 00h

- `f_ier_addr` → `/registers/registers/4` / `CH-f88915355b`
> Interrupt Enable 1 8 RW Enable/Mask interrupts

- `f_dlab_gate` → `/registers/registers/4` / `CH-f88915355b`
> At this time the above registers at addresses 0-1 can’t be accessed.

- `f_iir_pending` → `/sections/8/entries/3` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’. When it’s ‘1’ – no interrupt

- `f_iir_zero` → `/sections/8/entries/3` / `CH-f91cbf1c05`
> Bits 4 and 5: Logic ‘0’.

- `f_iir_one` → `/sections/8/entries/3` / `CH-f91cbf1c05`
> Bits 6 and 7: Logic ‘1’ for compatibility reason.

- `f_iir_reset` → `/sections/8/entries/3` / `CH-f91cbf1c05`
> Reset Value: C1h

- `f_reset_disabled` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> All interrupts are disabled in the Interrupt Enable Register.
