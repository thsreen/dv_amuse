# Reset-state scoreboard

Work package: `t_reset_state` · checks · NEEDS_REVIEW

## Dependent features

- `t_chip_reset`: reset values observable only after reset bring-up
- `t_wb_mon`: reset-state scoreboard needs monitor reconstruction of idle bus

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_init_cfg`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

After global reset top-level scoreboard reconstructs idle WISHBONE reads on observed wb_clk_i edges to check receiver/transmitter FIFOs and shift registers cleared, Divisor Latch 0, LCR 8N1, and IER interrupts disabled, depending on chip-reset bring-up and wishbone monitor.

## Preconditions

1. wb_clk_i running with fixed period before wb_rst_i assert and held fixed through reset-state checks
2. wb_rst_i owned by reset drive with no init_config_sequence before reset-state reads
3. wishbone_slave_interface monitor active reconstructing only completed ACK reads and flushing in-flight on wb_rst_i
4. uart_serial_data holds srx_pad_i at documented idle and observes stx_pad_o; modem_control_if holds cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i stable; interrupt_output observes int_o
5. LCR read uses documented bus pin value 3; Divisor IER IIR LSR pin values remain symbolic pending documented binding

## Stimulus pseudocode

```text
1. DRIVE wb_rst_i to documented active level via reset control
2. WAIT documented hold duration on observed wb_clk_i edges then DRIVE wb_rst_i to documented inactive level
3. WAIT documented deassert-to-access delay on observed wb_clk_i edges
4. READ LCR at wb_adr_i pin value 3 via wishbone_slave_interface driver [f_lcr_addr]
5. READ Divisor LSB MSB via DLAB-gated access and IER IIR LSR via symbolic addresses through wishbone_slave_interface driver without configuration writes [f_div_zero f_ier_disabled]
6. SAMPLE int_o via interrupt_output monitor and stx_pad_o idle via uart_serial_data monitor on observed wb_clk_i edges
```

## Check pseudocode

```text
1. COMPARE LCR read data to 00000011b for 8 bits no parity 1 stop [f_lcr_reset f_lcr_format]
2. COMPARE Divisor Latch value to 0 [f_div_zero]
3. COMPARE IER enables to disabled state where 0 means disabled [f_ier_disabled]
4. COMPARE LSR DR to 0 meaning no characters in FIFO to confirm FIFOs cleared [f_fifo_cleared f_lsr_dr]
5. COMPARE IIR bit0 to 1 meaning no interrupt pending with int_o negated to confirm interrupts disabled [f_ier_disabled f_iir_idle]
6. COMPARE no received or transmitted payload observed after reset to confirm shift registers and FIFOs cleared [f_shift_cleared f_fifo_cleared]
```

## Coverage pseudocode

```text
```

## Completion

1. COMPLETE when all reset-state COMPAREs evaluated after wb_rst_i deassert and reads sampled on observed wb_clk_i edges
2. TERMINATE on TEST_TIMEOUT_CYCLES operational limit; timeout is testbench limit not DUT timing

## Questions

1. What is documented active level polarity and inactive level of WB_RST_I on wb_rst_i, minimum assert duration in CLK cycles, and required deassert-to-first-read delay before reset-state reads?
2. What are documented bus pin values for IER IIR LSR and Divisor LSB MSB reads in DATA_BUS_WIDTH_8 build, DLAB gating for divisor access, wb_sel_i legal values, and address representation as pin values?
3. What are documented reset values for IER including reserved bits and for FCR trigger and clear bits, and how is FCR reset observed when all listed FCR bits are write-only or ignored?
4. What documented status proves receiver and transmitter FIFOs and shift registers cleared after reset: expected LSR DR OE PE FE BI and transmitter empty, IIR value and int_o level, and serial idle levels?
5. What is documented CLK sampling edge on wb_clk_i for wishbone monitor reconstruction and scoreboard sampling of reset-state reads?

## Essential blockers


## Specification evidence

- `f_fifo_cleared` → `/sections/1/entries/7` / `CH-1e2324cfc3`
> The receiver and transmitter FIFOs are cleared.

- `f_shift_cleared` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The receiver and transmitter shift registers are cleared

- `f_div_zero` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The Divisor Latch register is set to 0.

- `f_lcr_format` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The Line Control Register is set to communication of 8 bits of data, no parity, 1
> stop bit.

- `f_ier_disabled` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> All interrupts are disabled in the Interrupt Enable Register.

- `f_lcr_reset` → `/registers/registers/7` / `CH-bc7559f2ec`
> Reset Value: 00000011b

- `f_lcr_addr` → `/registers/registers/7` / `CH-f88915355b`
> Line Control Register 3 8 RW Control connection

- `f_lsr_dr` → `/sections/8/entries/6` / `CH-a2dd758e55`
> No characters in the FIFO

- `f_iir_idle` → `/sections/8/entries/3` / `CH-f91cbf1c05`
> no interrupt
> is pending

- `f_fcr_reset` → `/sections/12/entries/1` / `CH-dfb1048908`
> Reset Value : 11000000b
