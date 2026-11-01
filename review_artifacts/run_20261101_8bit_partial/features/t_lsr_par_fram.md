# LSR parity framing checks

Work package: `t_lsr_par_fram` · check · NEEDS_REVIEW

## Dependent features

- `t_uart_cfg`: LSR parity framing indications require configured line format before error injection and read-clear observation.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_wb_acc_cov`, `t_wb_mon`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Require LSR bit2 parity and bit3 framing to report 1 for top-of-FIFO erroneous character with read-clear and Receiver Line Status interrupt, verified via serial_data injection and wishbone_bus LSR reads after t_uart_cfg line-format setup.

## Preconditions

1. Dependency t_uart_cfg complete: LCR line format and divisor programmed via wishbone_bus; serial_data data_bits parity stop_bits bit_cycles agree symbolically with programmed format
2. Clock stable at fixed TESTBENCH period; reset driven to symbolic inactive level and released before stimulus
3. Ownership: wishbone_bus drives wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i; serial_data drives srx_pad_i; modem_control_if drives cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i to stable symbolic idle; observe wb_dat_o wb_ack_o int_o stx_pad_o rts_pad_o dtr_pad_o
4. Symbolic bindings: SYM_LSR_ADDR is actual 3-bit wb_adr_i pin value for LSR; SYM_LCR_PARITY and SYM_STOP track configured format; SYM_BIT_CYCLES tracks divisor timing; unknown LSR reset is null

## Stimulus pseudocode

```text
1. STAGE parity_directed: SPAWN serial_data child driving only srx_pad_i with one frame with inverted parity bit under SYM_LCR_PARITY [f_pe_top]; SPAWN wishbone_bus child driving only WB inputs to read SYM_LSR_ADDR; WAIT both complete
2. STAGE framing_directed: SPAWN serial_data child driving only srx_pad_i with one frame with missing stop bit held at 0 where 1 expected [f_fe_top] [f_first_stop]; SPAWN wishbone_bus child driving only WB inputs to read SYM_LSR_ADDR; WAIT both complete
3. STAGE clean_recovery: SPAWN serial_data child driving only srx_pad_i with clean frame matching SYM_LCR_PARITY and valid first stop [f_pe_zero] [f_fe_zero]; SPAWN wishbone_bus child driving only WB inputs to read SYM_LSR_ADDR; WAIT both complete
4. IF additional FIFO depth needed THEN REPEAT parity or framing injection before pop to keep error at top; ELSE proceed to checks
```

## Check pseudocode

```text
1. COMPARE LSR bit2 equals 1 when serial_data monitor reports top-of-FIFO character with parity error against LCR parity [f_pe_top]
2. COMPARE second LSR read via wishbone_bus at SYM_LSR_ADDR shows bit2 cleared after first LSR read [f_pe_clear]
3. COMPARE LSR bit3 equals 1 when serial_data monitor reports top-of-FIFO character without valid stop bit with only first stop checked [f_fe_top] [f_first_stop]
4. COMPARE second LSR read via wishbone_bus at SYM_LSR_ADDR shows bit3 cleared after first LSR read [f_fe_clear]
5. COMPARE LSR bit2 equals 0 and bit3 equals 0 on clean frame with correct parity and stop [f_pe_zero] [f_fe_zero]
6. COMPARE uart_interrupt int_o asserted while PE or FE set with IIR Receiver Line Status source until LSR read clears it [f_rls_int]
```

## Coverage pseudocode

```text
```

## Completion

1. WAIT all spawned serial_data and wishbone_bus children complete OR UNTIL TESTBENCH request_timeout_cycles expires as operational limit only
2. DRAIN wishbone_bus and serial_data monitors for drain_cycles as TESTBENCH operational limit then close virtual sequence
3. CLEANUP return wishbone_bus to idle symbolic levels via its driver, release explicit sequencer handles, leave srx_pad_i and modem inputs at symbolic idle

## Questions

1. Confirm parity and framing error latching and clear semantics including whether second LSR read shows 0 and top-of-FIFO advancement after Receiver Buffer pop?
2. What is actual 3-bit wb_adr_i pin value for LSR read, address representation, and legal wb_sel_i wb_we_i wb_stb_i wb_cyc_i levels for reads?
3. What is active level of wb_rst_i and inactive levels of wb_stb_i wb_cyc_i srx_pad_i cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and active level of int_o?
4. What LCR parity-enable even stick and stop settings enable parity and framing detection, and how must serial_data data_bits parity stop_bits bit_cycles agree with configuration bus writes and divisor?
5. What is expected receiver handling when more than one stop bit is generated given only first stop bit is checked?
6. What are TESTBENCH request_timeout_cycles drain_cycles and WB_ACK_O latency for LSR poll and error injection stages?

## Essential blockers


## Specification evidence

- `f_pe_top` → `/sections/8/entries/10` / `CH-a2dd758e55`
> The character that is currently at the top of the FIFO
> has been received with parity error.

- `f_pe_clear` → `/registers/registers/9/fields/2` / `CH-a2dd758e55`
> has been received with parity error. The bit is cleared upon reading
> from the register. Generates Receiver Line Status interrupt.

- `f_pe_zero` → `/registers/registers/9/fields/2` / `CH-a2dd758e55`
> No parity error in the current character

- `f_fe_top` → `/sections/8/entries/11` / `CH-a2dd758e55`
> The received character at the top of the FIFO did not
> have a valid stop bit.

- `f_fe_clear` → `/registers/registers/9/fields/3` / `CH-a2dd758e55`
> did not
> have a valid stop bit. Of course, generally, it might be that all the
> following data is corrupt. The bit is cleared upon reading from the
> register. Generates Receiver Line Status interrupt.

- `f_fe_zero` → `/registers/registers/9/fields/3` / `CH-a2dd758e55`
> No framing error in the current character

- `f_rls_int` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Parity, Overrun or Framing
> errors or Break Interrupt
> Reading the Line
> Status Register

- `f_first_stop` → `/registers/registers/7/fields/1` / `CH-bc7559f2ec`
> Note that the receiver always checks the first stop bit only.
