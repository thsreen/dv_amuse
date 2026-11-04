# Divisor latch coverage

Work package: `t_divisor_cov` · coverage · NEEDS_REVIEW

## Dependent features

- `t_wb_init_cfg`: LSB MSB zero maximum divisor coverage needs DLAB-gated programming

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Cover DLAB-gated divisor latch programming with LSB MSB zero max and combined value bins sampled on Wishbone write completions with DLAB 1.

## Preconditions

1. Common clock running and chip reset completed via common reset leaving divisor 0 disabling I/O [f_div_zero]
2. wishbone_slave_interface agent owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i and observes wb_dat_o wb_ack_o using 3-bit pin values 0 and 1 for LSB MSB [f_lsb_addr f_msb_addr]
3. LCR DLAB mechanism available: DLAB 1 selects divisor latches DLAB 0 selects normal registers; start with DLAB 0 idle [f_dlab_gating f_dlab_bit f_dlab_restore]
4. Other DUT inputs owned by their agents per existing_agent_ids with clock and reset as common UVCs; no reset polarity or inactive levels assumed

## Stimulus pseudocode

```text
1. STAGE bring_up via wishbone_slave_interface only: WRITE LCR with DLAB 1 using symbolic LCR address; WAIT wb_ack_o completion on clock [f_dlab_gating f_dlab_bit f_dlab_restore]
2. STAGE divisor_program with DLAB 1: FOR each pair in zero 0x00_0x00 min 0x01_0x01 symbolic_mid_low symbolic_mid_high max 0xFF_0xFF plus cross 0x00_0xFF and 0xFF_0x00: WRITE wb_adr_i 1 with MSB value THEN WRITE wb_adr_i 0 with LSB value; WAIT each wb_ack_o completion [f_msb_addr f_lsb_addr f_div_order f_div_single f_div_both]
3. STAGE dlab_return: WRITE LCR with DLAB 0 using symbolic LCR address; WAIT completion; IF normal alias needed THEN WRITE normal register at adr 0_1 with DLAB 0 to sample dlab_0_normal; WAIT completion [f_dlab_bit f_dlab_restore]
4. Cleanup: LEAVE DLAB 0 with wishbone bus idle-owned for handoff; no VIF delays in virtual control [f_dlab_restore]
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. SAMPLE cg_dlab_divisor on each wishbone write completion on clock edges via wishbone_slave_interface monitor analysis port: cp_dlab from LCR DLAB, cp_div_lsb from data at adr 0 when DLAB 1, cp_div_msb from data at adr 1 when DLAB 1; single UART instance per-instance false [f_dlab_gating f_dlab_bit f_lsb_addr f_msb_addr]
2. SAMPLE rc_divisor_bytes cp_divisor_value on DLAB 1 completions combining LSB plus MSB as single 16-bit value; IGNORE access_with_DLAB_0; cover lsb_zero mid max msb_zero mid max combined_zero_disables versus combined_nonzero_enables [f_div_single f_div_both f_div_zero]
```

## Completion

1. Done when LSB zero 0x00 min 0x01 mid_low mid_high max 0xFF and MSB zero min mid_low mid_high max with DLAB 1 plus combined_zero_disables and combined_nonzero_enables SAMPLED and DLAB restored to 0 with wishbone bus idle-owned [f_lsb_addr f_msb_addr f_div_single f_div_zero]
2. Bound by TEST_TIMEOUT_CYCLES operational limit; timeout is testbench limit not DUT timing; cleanup leaves DLAB 0 [f_dlab_restore]

## Questions

1. What are documented legal divisor values including zero and maximum handling for bins? Is combined 0x0000 only disabling I/O versus illegal and is 0xFFFF legal maximum for combined_zero_disables versus combined_nonzero_enables?
2. What are reset values of LSB at address 0 and MSB at address 1 for mirror comparison masks? Documented reset is empty so unknown reset must be null.

## Essential blockers


## Specification evidence

- `f_lsb_addr` → `/registers/registers/0` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor

- `f_msb_addr` → `/registers/registers/3` / `CH-f88915355b`
> Divisor Latch Byte 2 1 8 RW The MSB of the divisor

- `f_dlab_gating` → `/registers/registers/0` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set
> to ‘1’. At this time the above registers at addresses 0-1 can’t be accessed.

- `f_dlab_bit` → `/registers/registers/7/fields/6` / `CH-bc7559f2ec`
> ‘1’ – The divisor latches can be accessed
>  ‘0’ – The normal registers are accessed

- `f_div_single` → `/sections/1/entries/8` / `CH-06bad6ffcd`
> The 2 bytes form one 16-bit register, which is
> internally accessed as a single number.

- `f_div_both` → `/sections/1/entries/8` / `CH-06bad6ffcd`
> You should therefore set all 2 bytes of the register
> to ensure normal operation.

- `f_div_order` → `/sections/1/entries/8` / `CH-06bad6ffcd`
> The internal counter starts to work when the LSB of DL is written, so when setting the
> divisor, write the MSB first and the LSB last.

- `f_div_zero` → `/sections/1/entries/8` / `CH-06bad6ffcd`
> The register is set to the default value of 0 on reset, which
> disables all serial I/O operations in order to ensure explicit setup of the register in the
> software.

- `f_dlab_restore` → `/sections/1/entries/8` / `CH-06bad6ffcd`
> The divisor latches can be accessed by setting the 7th bit of LCR to ‘1’. You should
> restore this bit to ‘0’ after setting the divisor latches in order to restore access to the other
> registers that occupy the same addresses.
