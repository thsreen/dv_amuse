# WISHBONE init config sequence

Work package: `t_wb_init_cfg` · verification_plan · NEEDS_REVIEW

## Dependent features

- `t_chip_reset`: DLAB divisor FIFO IER programming is valid only after asynchronous reset bring-up

## Independent features

`t_clk_cov`, `t_irq_baud_mon`, `t_irq_id_cov`, `t_reset_state`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Directed init_config_sequence on wishbone_slave_interface_agent after chip_reset: set LCR DLAB 1, program Divisor MSB first LSB next, clear DLAB 0, then program FIFO trigger and IER enables using only documented addresses order and enable polarity with symbolic bring-up values.

## Preconditions

1. chip_reset done before any config: wb_clk_i stable at P_fixed owned by clock UVC and reset on wb_rst_i deasserted owned by reset UVC; polarity and cycles per t_chip_reset not inferred [f_init_divreset]
2. wishbone_slave_interface_agent active master owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i and observes wb_dat_o wb_ack_o; addresses are 3-bit pin values 0-3 [f_addr_lcr,f_addr_divlsb,f_addr_divmsb,f_addr_ier,f_addr_fcr]; 8-bit data [f_bus8]; other DUT inputs idle-owned: srx_pad_i by uart_serial_data cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i by modem_control_if
3. post-reset state: Divisor 0 FIFOs cleared IER disabled LCR 8N1 [f_init_divreset,f_init_lcrfmt,f_init_ier]; symbolic knobs DIV_MSB_SYM DIV_LSB_SYM TRIGGER_SYM IER_EN_SYM unresolved pending questions

## Stimulus pseudocode

```text
1. WAIT for chip_reset done with wb_clk_i stable; IF TEST_TIMEOUT_CYCLES THEN abort
2. WRITE LCR DLAB=1 via wishbone_register_access: wb_adr_i=3b011 wb_dat_i={LCR_HOLD_SYM[6:0],1b1} [f_init_dlab1,f_addr_lcr]; WAIT wb_ack_o
3. WRITE Divisor MSB first: wb_adr_i=3b001 wb_dat_i=DIV_MSB_SYM [f_init_divorder,f_addr_divmsb,f_dlab_gate]; WAIT wb_ack_o
4. WRITE Divisor LSB next: wb_adr_i=3b000 wb_dat_i=DIV_LSB_SYM [f_init_divorder,f_addr_divlsb]; WAIT wb_ack_o
5. WRITE LCR DLAB=0: wb_adr_i=3b011 wb_dat_i={LCR_HOLD_SYM[6:0],1b0} [f_init_dlab0,f_addr_lcr]; WAIT wb_ack_o
6. WRITE FCR trigger: wb_adr_i=3b010 wb_dat_i={TRIGGER_SYM[1:0],4b0000,2b00} with trigger per [f_fcr_trigdef,f_fcr_trig14] and clears 0 per [f_fcr_clear] [f_addr_fcr,f_init_fifotrig]; WAIT wb_ack_o
7. WRITE IER enables with DLAB=0: wb_adr_i=3b001 wb_dat_i={4b0000,IER_EN_SYM[3:0]} reserved 0 [f_addr_ier,f_ier_bit0,f_ier_en,f_ier_dis,f_ier_reserved,f_init_ier]; WAIT wb_ack_o
```

## Check pseudocode

```text
1. READ IER via wishbone_register_access at wb_adr_i=3b001 with DLAB=0 then COMPARE dat_o[3:0] to IER_EN_SYM and COMPARE dat_o[7:4]==4b0000; FAIL on mismatch [f_ier_bit0,f_ier_en,f_ier_dis,f_ier_reserved]
2. No READ check on FCR address: FCR is W-only so trigger is not observable by read-back; observability pending question [f_fcr_trigdef]
```

## Coverage pseudocode

```text
1. SAMPLE cg_dlab_divisor via dedicated subscriber on wishbone monitor analysis port on each divisor-byte write completion: cp_dlab cp_div_lsb cp_div_msb [f_dlab_gate,f_addr_divlsb,f_addr_divmsb]
2. SAMPLE rc_divisor_bytes on same event for lsb_zero/mid/max msb_zero/mid/max combined values with ignore_bins access_with_DLAB_0 excluded [f_init_divorder]
```

## Completion

1. Done when LCR-DLAB1 plus MSB-first plus LSB-next plus LCR-DLAB0 plus FCR-trigger plus IER-enable writes all ACKed and IER read-back COMPARE passes and divisor coverage SAMPLED
2. Bound by TEST_TIMEOUT_CYCLES operational limit; timeout is testbench limit not DUT timing; cleanup leaves DLAB=0 with wishbone bus idle-owned for traffic handoff

## Questions

1. What symbolic divisor LSB/MSB values form legal nonzero divisor for bring-up and is divisor 0 illegal beyond reset value 0 and MSB-first LSB-next order?
2. What specific FCR trigger selection 00-1B 01-4B 10-8B 11-14B is required for bring-up given 14 bytes only recommended if system responds fast enough?
3. What specific IER bits 3-0 enables are desired for bring-up versus later traffic?
4. What LCR bits 6-0 line parameters must accompany DLAB 1 then DLAB 0 during init?
5. How is FCR trigger observed when all listed bits are write-only or ignored and what is post-reset trigger level?
6. What documented deassert-to-first-write delay is required after wb_rst_i before init_config_sequence?

## Essential blockers


## Specification evidence

- `f_init_dlab1` → `/sections/10/entries/5` / `CH-1e2324cfc3`
> Set bit 7 to ‘1’

- `f_init_dlab0` → `/sections/10/entries/5` / `CH-1e2324cfc3`
> Set bit 7 of LCR to ‘0’ to disable access to Divisor Latches.

- `f_init_divorder` → `/sections/10/entries/5` / `CH-1e2324cfc3`
> Set the Divisor Latches, MSB first, LSB next.

- `f_init_divreset` → `/sections/10/entries/5` / `CH-1e2324cfc3`
> The Divisor Latch register is set to 0.

- `f_init_fifotrig` → `/sections/10/entries/5` / `CH-1e2324cfc3`
> Set the FIFO trigger level.

- `f_init_ier` → `/sections/10/entries/5` / `CH-1e2324cfc3`
> Enable desired interrupts by setting appropriate bits in the Interrupt Enable

- `f_init_lcrfmt` → `/sections/10/entries/5` / `CH-1e2324cfc3`
> The Line Control Register is set to communication of 8 bits of data, no parity, 1

- `f_dlab_gate` → `/sections/9/entries/1` / `CH-f88915355b`
> At this time the above registers at addresses 0-1 can’t be accessed.

- `f_addr_lcr` → `/sections/9/entries/1` / `CH-f88915355b`
> Line Control Register 3 8 RW Control connection

- `f_addr_divlsb` → `/sections/9/entries/1` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor

- `f_addr_divmsb` → `/sections/9/entries/1` / `CH-f88915355b`
> Divisor Latch Byte 2 1 8 RW The MSB of the divisor

- `f_addr_ier` → `/sections/9/entries/1` / `CH-f88915355b`
> Interrupt Enable 1 8 RW Enable/Mask interrupts

- `f_addr_fcr` → `/sections/9/entries/1` / `CH-f88915355b`
> FIFO Control 2 8 W Control FIFO options

- `f_fcr_trigdef` → `/sections/12/entries/1` / `CH-dfb1048908`
> Define the Receiver FIFO Interrupt trigger level

- `f_fcr_trig14` → `/sections/12/entries/1` / `CH-dfb1048908`
> ‘11’ – 14 bytes

- `f_fcr_clear` → `/sections/12/entries/1` / `CH-dfb1048908`
> Writing a ‘1’ to bit 1 clears the Receiver FIFO

- `f_ier_bit0` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 0 RW Received Data available interrupt

- `f_ier_en` → `/sections/8/entries/2` / `CH-de51b2eafc`
> ‘1’ – enabled

- `f_ier_dis` → `/sections/8/entries/2` / `CH-de51b2eafc`
> ‘0’ – disabled

- `f_ier_reserved` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 7-4 RW Reserved. Should be logic ‘0’.

- `f_bus8` → `/sections/10/entries/5` / `CH-d62a4ba2db`
> It has an 8-bit data bus for compatibility reason.
