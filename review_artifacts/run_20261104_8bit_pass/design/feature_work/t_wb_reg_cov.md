# WISHBONE register coverage

Work package: `t_wb_reg_cov` · coverage · NEEDS_REVIEW

## Dependent features

- `t_wb_mon`: register address direction coverage needs sampled transactions

## Independent features

`t_addr_dlab_cov`, `t_chip_reset`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_init_cfg`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Cover WISHBONE slave accesses at bus pin values 0-6 with read/write direction and byte data classes and documented per-address access types, sampled from completed transactions with DLAB 0 for normal registers.

## Preconditions

1. Clock configured to fixed period per test; monitor observes wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i on CLK edges [f_bus8_1].
2. Reset completed with monitor flushing in-flight transfer; DLAB tracked and cleared to 0 to select normal registers at addr 0-1 [f_dlab_block_1] [f_dlab_gate_1].
3. wishbone_slave_interface owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i and observes wb_dat_o wb_ack_o; dedicated coverage subscribers tap monitor analysis port.
4. Divisor alias at addr 0-1 when DLAB mismatches assigned to ignore_bins divisor_alias_when_DLAB_mismatch [f_dllsb_1].

## Stimulus pseudocode

```text
1. FOR each addr IN 0 to 6 with wb_adr_i pin value equal addr AND DLAB equal 0: drive only documented directions: IF addr 0 THEN read for RBR [f_rbr_1] and write for THR [f_thr_1]; IF addr 1 THEN read and write for IER [f_ier_1]; IF addr 2 THEN read for IIR [f_iir_1] and write for FCR [f_fcr_1]; IF addr 3 THEN read and write for LCR [f_lcr_1]; IF addr 4 THEN write for MCR [f_mcr_1]; IF addr 5 THEN read for LSR [f_lsr_1]; IF addr 6 THEN read for MSR [f_msr_1].
2. FOR each write drive wb_dat_i values covering byte classes 0x00 0x01 0x02_0x7F 0x80_0xFE 0xFF; FOR each read SAMPLE wb_dat_o into same classes; drive all transfers only via wishbone_slave_interface.
3. WAIT for monitor-reported completed transaction on wb_ack_o observed on CLK edges before next drive; FOR illegal addr_7 drive at most one probe if needed for illegal_bins and do not count toward normal bins.
4. IF reset occurs THEN FLUSH in-flight, WAIT for reset completion, re-establish DLAB equal 0, then RESUME remaining addr direction data-class combinations.
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. SAMPLE each completed transaction reported by wishbone_slave_interface monitor on wb_ack_o observed on CLK edges; use dedicated coverage subscribers tapping monitor analysis port.
2. SAMPLE cg_wb_reg_access cp_wb_addr with bins addr_0 addr_1 addr_2 addr_3 addr_4 addr_5 addr_6 and illegal_bins addr_7; cp_wb_dir with read_WE0 from wb_we_i read and write_WE1 from wb_we_i write; cp_wb_data_class from byte on wb_dat_i for writes and wb_dat_o for reads with bins data_zero_0x00 data_min_0x01 data_mid_low_0x02_0x7F data_mid_high_0x80_0xFE data_max_0xFF.
3. SAMPLE rc_wb_regs cp_reg_addr_access with bins reg0_R_RBR reg0_W_THR reg1_RW_IER reg2_R_IIR reg2_W_FCR reg3_RW_LCR reg4_W_MCR reg5_R_LSR reg6_R_MSR qualified by DLAB equal 0 for addr 0-1, with illegal_bins addr_7 and ignore_bins divisor_alias_when_DLAB_mismatch.
4. Set per-instance false single UART instance with clock period fixed per test; do not count divisor alias at addr 0-1 when DLAB mismatches normal selection.
```

## Completion

1. Terminate when directed accesses to pin values 0-6 with documented directions and byte classes are attempted and monitor reports traffic done, or on TEST_TIMEOUT_CYCLES operational limit; timeout is testbench limit not DUT timing.
2. Cleanup by stopping wishbone_slave_interface stimulus, allowing in-flight to flush on reset, and closing dedicated coverage sampling.

## Questions

1. What is CLK sampling edge, wb_rst_i polarity and required reset duration in CLK cycles, and must monitor flush versus flag reset-during-transfer?
2. What are documented handshake semantics for wb_adr_i wb_we_i wb_sel_i wb_stb_i wb_cyc_i stability, wb_ack_o single versus multi-cycle window, wb_dat_o validity on reads, and back-to-back handling?
3. What is documented wb_sel_i legal values in 8-bit build, address representation as pin values 0-6 versus offsets, and illegal addr_7 handling?
4. What is expected handling of mismatched direction per address for rc_wb_regs bins: read from W-only THR FCR MCR and write to R-only RBR IIR LSR MSR ignored versus illegal versus defined return?
5. What are legal write masks and read return values for IER reserved bits, FCR ignored bits, and reset values for comparison versus coverage byte classes 0x00 0x01 0x02_0x7F 0x80_0xFE 0xFF?
6. How is FCR reset value observed when bits are write-only or ignored, and what LCR bit 7 sequence guarantees DLAB 0 setup for normal 0-1 coverage?

## Essential blockers


## Specification evidence

- `f_rbr_1` → `/registers/registers/1` / `CH-f88915355b`
> Receiver Buffer 0 8 R Receiver FIFO output

- `f_thr_1` → `/registers/registers/2` / `CH-f88915355b`
> 0 8 W Transmit FIFO input

- `f_ier_1` → `/sections/9/entries/8` / `CH-f88915355b`
> Interrupt Enable 1 8 RW Enable/Mask interrupts

- `f_iir_1` → `/sections/9/entries/8` / `CH-f88915355b`
> Interrupt Identification 2 8 R Get interrupt information

- `f_fcr_1` → `/sections/9/entries/8` / `CH-f88915355b`
> FIFO Control 2 8 W Control FIFO options

- `f_lcr_1` → `/sections/9/entries/8` / `CH-f88915355b`
> Line Control Register 3 8 RW Control connection

- `f_mcr_1` → `/sections/9/entries/8` / `CH-f88915355b`
> Modem Control 4 8 W Controls modem

- `f_lsr_1` → `/sections/9/entries/8` / `CH-f88915355b`
> Line Status 5 8 R Status information

- `f_msr_1` → `/sections/9/entries/8` / `CH-f88915355b`
> Modem Status 6 8 R Modem Status

- `f_dlab_block_1` → `/sections/9/entries/8` / `CH-f88915355b`
> At this time the above registers at addresses 0-1 can’t be accessed.

- `f_dlab_gate_1` → `/sections/9/entries/1` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set

- `f_dllsb_1` → `/sections/9/entries/1` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor

- `f_bus8_1` → `/sections/4/strategy/agents/0` / `CH-d62a4ba2db`
> It has an 8-bit data bus for compatibility reason.
