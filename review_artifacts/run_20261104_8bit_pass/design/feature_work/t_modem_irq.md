# Modem-status interrupt

Work package: `t_modem_irq` · checks · NEEDS_REVIEW

## Dependent features

- `t_traffic_seq`: CTS DSR RI DCD toggle stimulus comes from traffic modem toggles

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_reset_state`, `t_top_virtual`, `t_uart_mon`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Verify modem status interrupt where CTS DSR RI DCD toggles set MSR deltas cleared by MSR read and assert INT_O with IIR Modem Status only when IER bit3 enabled checked in modem agent and top scoreboard in normal mode with DLAB 0

## Preconditions

1. Bind modem_control_if to cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i drive plus rts_pad_o dtr_pad_o observe and interrupt_output to int_o observe and wishbone_slave_interface to wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i with wb_clk_i owned by clock and wb_rst_i owned by reset via common UVCs with polarity symbolic
2. Own every DUT input with uart_serial_data owning srx_pad_i tied idle for this feature and no floating inputs and all outputs observed only
3. Require normal operation MCR Loopback 0 with LCR DLAB 0 so modem registers accessible with MSR read at wb_adr_i pin value 6 width 8 read only and IER IIR pin values symbolic
4. Start from reset cleared FIFOs with all IER disabled then program divisor line FIFO base and IER bit3 per case 0 disabled versus 1 enabled

## Stimulus pseudocode

```text
1. STAGE0_BRINGUP: wishbone_slave_interface WRITES divisor line FIFO base with LCR DLAB 0 and MCR Loopback 0 normal mode; WAIT reset release; BOUND by drain_cycles operational limit
2. STAGE1_DISABLED: wishbone_slave_interface WRITES IER bit3 0; FOR each line IN cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i: modem_control_if DRIVES single toggle via custom driver_body using modem_handshake_toggle test only infrastructure; wishbone_slave_interface READS MSR at pin 6; interrupt_output OBSERVES int_o via monitor_body
3. STAGE2_ENABLED: wishbone_slave_interface WRITES IER bit3 1; FOR each line IN cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i: modem_control_if DRIVES single toggle; wishbone_slave_interface READS MSR and IIR; interrupt_output OBSERVES int_o; per agent sequences drive only own interface and stages execute in order with concurrent wishbone modem interrupt observation
4. VIRTUAL_SPAWN_ONLY: virtual sequence SPAWNS listed per agent sequences with no VIFs or delays
5. STAGE3_CLEAR: wishbone_slave_interface READS MSR to clear deltas; WAIT drain_cycles; CLEANUP restores MCR Loopback 0 and LCR DLAB 0 with bus idle owned
```

## Check pseudocode

```text
1. COMPARE MSR delta DCTS DDSR TERI DDCD set after corresponding cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i toggle and cleared after MSR read in modem agent and top scoreboard
2. COMPARE MSR status bits 4 to 7 complement of CTS DSR RI DCD in normal mode versus loopback remap excluded
3. COMPARE int_o negated when IER bit3 is 0 despite delta versus asserted when IER bit3 is 1 with IIR bit0 0 pending
4. COMPARE IIR bits 3 to 1 equals 000 4th Modem Status with reset control reading MSR and bit0 1 idle after clear respecting higher priority preemption
5. COMPARE top scoreboard end to end modem toggle to MSR to int_o to IIR with no loss duplication or misorder
```

## Coverage pseudocode

```text
```

## Completion

1. Done when IER disabled case shows MSR delta without int_o plus IER enabled cases show MSR delta with int_o and IIR 000 for each of CTS DSR RI DCD each with at least one scoreboard COMPARE
2. Bound by TEST_TIMEOUT_CYCLES plus drain_cycles and request_timeout_cycles operational limits where timeout is testbench limit not DUT timing
3. Cleanup restores MCR Loopback 0 and LCR DLAB 0 with wishbone bus idle owned for handoff

## Questions

1. What are confirmed wb_adr_i pin values for IER and IIR under DLAB 0 versus divisor under DLAB 1 plus wb_sel_i handling and reset release to first access delay
2. What is wb_rst_i polarity and int_o active polarity for assertion versus negation correlation with IIR bit0
3. What are inactive drive levels for cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and tie off for srx_pad_i and idle ownership of wishbone bus during modem toggles
4. What exact IIR bits 3 to 1 and bit0 encoding must be observed for isolated Modem Status 000 versus concurrent higher priority RLS RDA Timeout THRE including bits 7 to 4
5. What MCR Loopback 0 versus 1 handling applies for normal external modem observation and are external modem inputs ignored in loopback when STX is held at 1

## Essential blockers


## Specification evidence

- `f_modem_irq_1` → `/sections/8/entries/10` / `CH-f91cbf1c05`
> 0 0 0 4 th Modem Status CTS, DSR, RI or DCD. Reading the Modem
> status register.

- `f_iir_pending_1` → `/sections/8/entries/3` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’. When it’s ‘1’ – no interrupt
> is pending.

- `f_iir_prio_1` → `/sections/8/entries/4` / `CH-f91cbf1c05`
> 0 0 0 4 th Modem Status CTS, DSR, RI or DCD. Reading the Modem
> status register.

- `f_ier_bit3_1` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 3 RW Modem Status Interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled

- `f_ier_general_1` → `/sections/8/entries/2` / `CH-de51b2eafc`
> This register allows enabling and disabling interrupt generation by the UART.

- `f_msr_delta_1` → `/registers/registers/10` / `CH-0174a058ac`
> These bits are set to
> ‘1’ when a change in corresponding line has been detected and they are reset when the
> register is being read.

- `f_msr_dcts_1` → `/registers/registers/10/fields/0` / `CH-0174a058ac`
> ‘1’ – The CTS line has changed its state.

- `f_msr_ddsr_1` → `/registers/registers/10` / `CH-0174a058ac`
>  ‘1’ – The DSR line has changed its state.

- `f_msr_teri_1` → `/registers/registers/10` / `CH-0174a058ac`
> Trailing Edge of Ring Indicator  (TERI) detector. The RI line has
> changed its state from low to high state.

- `f_msr_ddcd_1` → `/registers/registers/10` / `CH-0174a058ac`
>  ‘1’ – The DCD line has changed its state.

- `f_msr_addr_1` → `/registers/registers/10` / `CH-f88915355b`
> Modem Status 6 8 R Modem Status

- `f_reset_ier_1` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> All interrupts are disabled in the Interrupt Enable Register.

- `f_modem_func_1` → `/interfaces/groups/5/property_evidence/function` / `CH-6abe65aeff`
> The modem control register allows transferring control signals to a modem connected to
> the UART.

- `f_loopback_1` → `/interfaces/groups/5/property_evidence/function` / `CH-6abe65aeff`
>  ‘0’ – normal operation
>  ‘1’ – loopback mode. When in loopback mode, the Serial
> Output Signal (STX_PAD_O) is set to logic ‘1’.
