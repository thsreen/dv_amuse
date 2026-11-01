# Reset divisor and known outputs

Work package: `t_reset_div_known` · check · NEEDS_REVIEW

## Dependent features

- `t_bringup_clk`: Divisor zero and known non-XZ outputs require reset deassertion order.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_uart_cfg`, `t_wb_acc_cov`, `t_wb_mon`, `t_wb_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

After WB_RST_I deassertion on fixed symbolic clock, verify Divisor Latch reads zero via DLAB-gated reads and DUT outputs leave X/Z to known state, after bring-up reset order.

## Preconditions

1. Bring-up reset order from t_bringup_clk available: assert then deassert via reset with symbolic active level on fixed symbolic clock period
2. Clock is running; WAIT durations are symbolic clock cycles with no DUT timing claim
3. wishbone_bus owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i and serial_data owns srx_pad_i and modem_control_if owns cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i
4. Divisor not yet programmed; divisor access requires DLAB=1 per documented gating

## Stimulus pseudocode

```text
1. ASSERT reset to SYM_RESET_ACTIVE and WAIT SYM_RESET_CYCLES clock cycles [f_reset_port]
2. DEASSERT reset then WAIT SYM_IDLE_CYCLES clock cycles on clock for post-reset settle
3. DRIVE idle via wishbone_bus and via serial_data on srx_pad_i and via modem_control_if on cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i with no traffic
4. WRITE LCR DLAB to 1 via wishbone_bus to enable divisor access [f_dlab_gate]
5. READ address 0 via wishbone_bus to SAMPLE DIV_LSB and READ address 1 via wishbone_bus to SAMPLE DIV_MSB [f_lsb_map f_msb_map]
6. WRITE LCR DLAB to 0 via wishbone_bus to restore normal register map [f_dlab_gate]
```

## Check pseudocode

```text
1. SAMPLE wb_dat_o wb_ack_o stx_pad_o int_o rts_pad_o dtr_pad_o after WAIT SYM_IDLE_CYCLES and COMPARE each is-not X and is-not Z; FAIL on any X/Z [f_known_outputs f_reset_port]
2. COMPARE DIV_LSB == 0x00 and DIV_MSB == 0x00 and combined 16-bit divisor == 0x0000; REPORT non-zero as reset-value failure [f_div_zero f_lsb_map f_msb_map]
3. IF any output SAMPLE is X/Z or any divisor byte is non-zero THEN STOP and REPORT known-after-reset failure with no further traffic
```

## Coverage pseudocode

```text
```

## Completion

1. WAIT for both divisor reads and all output known-state samples to complete
2. ENFORCE TEST_TIMEOUT_CYCLES as testbench operational limit only, not DUT timing requirement
3. CLEANUP restore LCR DLAB to 0 and return wishbone_bus serial_data modem_control_if to idle

## Questions

1. What is active level and polarity of wb_rst_i and required assert hold plus deassert-to-access delay in clock cycles versus absolute time?
2. What is LCR bus address and exact write encoding to set and clear DLAB bit 7, and required wb_sel_i wb_we_i wb_stb_i wb_cyc_i values for 8-bit divisor access?
3. What are inactive idle levels for wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i srx_pad_i cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i during reset and idle?
4. Are output checks limited to known non-X/Z only, or what are exact post-reset 0/1 values for wb_dat_o wb_ack_o stx_pad_o int_o rts_pad_o dtr_pad_o?
5. How many clock cycles after WB_RST_I deassertion must be waited before divisor readback and output sampling for SYM_IDLE_CYCLES?
6. Are divisor addresses 0 and 1 actual pin values on 3-bit wb_adr_i in DATA_BUS_WIDTH_8 build and is any byte-lane handling required?

## Essential blockers


## Specification evidence

- `f_div_zero` → `/sections/5/entries/11` / `CH-1e2324cfc3`
> • The Divisor Latch register is set to 0.

- `f_lsb_map` → `/registers/registers/0` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor

- `f_msb_map` → `/registers/registers/3` / `CH-f88915355b`
> Divisor Latch Byte 2 1 8 RW The MSB of the divisor

- `f_dlab_gate` → `/registers/registers/0` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set

- `f_known_outputs` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> Upon reset the core performs the following tasks:

- `f_reset_port` → `/interfaces/groups/2` / `CH-63ad4d61a5`
> WB_RST_I 1 Input Asynchronous Reset
