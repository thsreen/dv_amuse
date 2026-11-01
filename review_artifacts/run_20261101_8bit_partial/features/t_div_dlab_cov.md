# Divisor latch coverage

Work package: `t_div_dlab_cov` · coverage · NEEDS_REVIEW

## Dependent features

- `t_uart_cfg`: Divisor zero max mid coverage crossed with access requires DLAB handling sweep programmed.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_wb_acc_cov`, `t_wb_mon`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Cover 8-bit divisor LSB at addr 0 and MSB at addr 1 across symbolic zero max mid values with LCR bit7 DLAB set-then-clear gating and cross of WISHBONE addr with DLAB state to prove divisor versus normal routing; INFERRED quick-test bins guide architecture only with DOCUMENTED facts as oracle.

## Preconditions

1. Clock stable at symbolic fixed period and reset completed via clock and reset without assuming polarity
2. Dependency t_uart_cfg programming order available for LCR DLAB set then divisor MSB-first LSB-next then DLAB clear [f_prog_msb_first f_prog_dlab_set f_prog_dlab_clear]
3. wishbone_bus owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i and observes wb_dat_o wb_ack_o as WISHBONE responder access
4. Bus addresses are 3-bit wb_adr_i pin values 0 for LSB DIV and 1 for MSB DIV with LCR at 3 [f_div_lsb_addr f_div_msb_addr]
5. DLAB is LCR bit 7 with 1 divisor and 0 normal and blocks opposite mapping at 0 to 1 [f_dlab_one f_dlab_zero f_dlab_gates_div f_dlab_blocks_norm]
6. Reset state divisor zero and LCR DLAB 0 [f_div_reset_zero f_lcr_reset]
7. TESTBENCH limits drain_cycles and request_timeout_cycles are symbolic operational limits only

## Stimulus pseudocode

```text
1. FOR each symbolic divisor corner in DIV_ZERO DIV_MAX DIV_MID_LOW DIV_MID_HIGH do divisor-gated writes via wishbone_bus only
2. WRITE LCR at wb_adr_i 3 with DLAB 1 via wishbone_bus driver to select divisor [f_dlab_one f_prog_dlab_set]
3. WRITE divisor MSB at wb_adr_i 1 then LSB at wb_adr_i 0 MSB-first LSB-next via wishbone_bus for current corner [f_div_msb_addr f_div_lsb_addr f_prog_msb_first]
4. WRITE LCR at wb_adr_i 3 with DLAB 0 via wishbone_bus to disable divisor and enable normal [f_dlab_zero f_prog_dlab_clear]
5. IF exercising gating THEN WRITE READ normal regs at wb_adr_i 0 to 1 with DLAB 0 and divisor at wb_adr_i 0 to 1 with DLAB 1 via wishbone_bus [f_dlab_blocks_norm f_dlab_gates_div]
6. WAIT wb_ack_o assertion per transfer as transfer completion without assuming DUT timing
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. SAMPLE cg_divisor_latch via dedicated subscriber tapping wishbone_bus monitor on completed divisor write with DLAB 1 [f_dlab_gates_div f_div_lsb_addr f_div_msb_addr]
2. SAMPLE div_lsb_value bins zero max mid_low mid_high via subscriber using observed wb_dat_i at addr 0 with DLAB 1 symbolic DIV_ZERO DIV_MAX DIV_MID values
3. SAMPLE div_msb_value bins zero max mid mid_high via subscriber using observed wb_dat_i at addr 1 with DLAB 1
4. SAMPLE cross_wb_dlab via dedicated subscriber tapping wishbone_bus monitor on wb_ack_o assertion with DLAB state [f_dlab_one f_dlab_zero f_dlab_blocks_norm]
5. SAMPLE wb_addr_x_dlab bins normal_0_dlab0 normal_1_dlab0 divlsb_0_dlab1 divmsb_1_dlab1 other_2to6_dlab0 other_2to6_dlab1 using wb_adr_i pin value and LCR bit7 state
6. NEVER sample coverage from driver items and never compare config writes as payload
```

## Completion

1. WAIT all spawned wishbone_bus divisor sequences complete OR UNTIL TESTBENCH request_timeout_cycles expires as operational limit only
2. DRAIN wishbone_bus monitor for drain_cycles as TESTBENCH operational limit then close virtual sequence
3. CLEANUP deassert wb_stb_i and wb_cyc_i via wishbone_bus driver and return wishbone_bus to idle leaving serial_data and modem_control_if untouched

## Questions

1. Confirm divisor values and cross with DLAB configuration including zero max and representative mid LSB MSB values and cross with register access gating?
2. Is divisor zero programmable or reset-only and are all 0x00 to 0xFF LSB MSB values legal, and what mid values and comparison masks define zero max mid coverage?
3. What is active level of wb_rst_i and inactive levels of wb_stb_i wb_cyc_i wb_we_i, legal wb_sel_i for 8-bit data, and WB_ACK_O latency and back-to-back idle rule for divisor and cross accesses?
4. What are owners or tie_offs for srx_pad_i cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and observers for stx_pad_o rts_pad_o dtr_pad_o int_o during divisor-only coverage?
5. How is DLAB state sampled for cross coverage and what are write read addresses for addr 7 and handling of DLAB-banked divisor mirrors without inventing reset?
6. What are concrete drain_cycles and request_timeout_cycles TESTBENCH limits and symbolic sweep control for directed zero max then mid exploration?

## Essential blockers


## Specification evidence

- `f_div_lsb_addr` → `/registers/registers/0` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor

- `f_div_msb_addr` → `/registers/registers/3` / `CH-f88915355b`
> Divisor Latch Byte 2 1 8 RW The MSB of the divisor

- `f_dlab_gates_div` → `/registers/registers/0` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set

- `f_dlab_blocks_norm` → `/registers/registers/3` / `CH-f88915355b`
> At this time the above registers at addresses 0-1 can’t be accessed.

- `f_dlab_one` → `/registers/registers/7/fields/6` / `CH-bc7559f2ec`
>  ‘1’ – The divisor latches can be accessed

- `f_dlab_zero` → `/registers/registers/7/fields/6` / `CH-bc7559f2ec`
>  ‘0’ – The normal registers are accessed

- `f_div_reset_zero` → `/sections/5/entries/11` / `CH-1e2324cfc3`
> • The Divisor Latch register is set to 0.

- `f_prog_msb_first` → `/sections/5/entries/11` / `CH-1e2324cfc3`
> • Set the Divisor Latches, MSB first, LSB next.

- `f_prog_dlab_set` → `/sections/5/entries/11` / `CH-1e2324cfc3`
> to allow access to the Divisor Latches.

- `f_prog_dlab_clear` → `/sections/5/entries/11` / `CH-1e2324cfc3`
> • Set bit 7 of LCR to ‘0’ to disable access to Divisor Latches.

- `f_lcr_reset` → `/registers/registers/7/fields/6` / `CH-bc7559f2ec`
> Reset Value: 00000011b
