# WISHBONE slave monitor

Work package: `t_wb_mon` · verification_plan · NEEDS_REVIEW

## Dependent features

- `t_clk_seq`: sampling on CLK needs fixed-period clock defined first

## Independent features

`t_chip_reset`, `t_clk_cov`, `t_divisor_cov`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_id_cov`, `t_line_err_cov`, `t_modem_irq`, `t_modem_traffic_cov`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_init_cfg`, `t_wb_top_seq`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Build wishbone_slave_interface monitor sampling RTL pins wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i on observed CLK edges from fixed-period clock, reconstructing completed read and write transactions on WB_ACK_O assertion for analysis port, flushing in-flight on wb_rst_i, with X or Z and known-after-reset checks and ACK-sampled register and DLAB coverage for 8-bit addresses 0-6.

## Preconditions

1. Clock active with fixed period P_fixed started before reset and held fixed through traffic with monitor sampling on observed CLK edges
2. Reset asserted via wb_rst_i before configuration and observed by monitor for flush with symbolic active level pending polarity answer
3. Monitor bound to wishbone_slave_interface RTL pins wb_clk_i wb_rst_i wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i in 8-bit build
4. Register address space 0 to 6 with DLAB aliasing at 0 to 1 defined for reconstruction and coverage

## Stimulus pseudocode

```text
1. SAMPLE wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i on each observed CLK edge into current sample
2. IF reset asserted THEN flush in-flight latched request and discard partial transaction and WAIT for reset deassertion before resuming reconstruction
3. IF WB_ACK_O asserted THEN latch address control and data from current sample and reconstruct one completed read or write transaction by WE value and EMIT to analysis port
4. FOR each emitted transaction CONTINUE sampling without driving DUT inputs and without inserting DUT timing delays
```

## Check pseudocode

```text
1. IF any sampled WB_ADDR_I or WB_SEL_I or WB_DAT_I or WB_DAT_O or WB_WE_I or WB_STB_I or WB_CYC_I or WB_ACK_O or CLK or WB_RST_I equals X or Z THEN report uvm_error immediately
2. AFTER reset deassertion CHECK DUT outputs wb_dat_o and wb_ack_o reach known non-X or Z values before first reconstruction
```

## Coverage pseudocode

```text
1. SAMPLE cg_wb_reg_access on WB_ACK_O assertion observed on CLK edges: cp_wb_addr addr_0 to addr_6 with illegal addr_7 and cp_wb_dir read_WE0 write_WE1 and cp_wb_data_class zero min mid_low mid_high max
2. SAMPLE cg_cross_addr_dlab on WB_ACK_O completion observed on CLK edges: cross address with DLAB covering addr0_dlab0_RBR_THR addr0_dlab1_DLL_SB addr1_dlab0_IER addr1_dlab1_DLM_SB addr2_to_6 variants with illegal addr_7_any_dlab
```

## Completion

1. Monitor runs through reset and traffic until test end with in-flight flushed on reset and only completed ACK transactions emitted
2. Terminate on traffic done or TEST_TIMEOUT_CYCLES operational limit; timeout is testbench limit not DUT timing

## Questions

1. What is active level polarity of wb_rst_i described as Asynchronous Reset and required reset duration in CLK cycles and must monitor flush in-flight transfer versus flag reset-during-transfer as error?
2. What are documented WISHBONE handshake semantics for reconstruction: stability of wb_adr_i wb_we_i wb_sel_i wb_stb_i wb_cyc_i during transfer and wb_ack_o assertion window single versus multi-cycle and wb_dat_o validity window on reads and back-to-back handling?
3. What is documented wb_sel_i usage in 8-bit build including legal values and ignored versus checked behavior and address representation as pin values 0-6 versus offsets and illegal addr_7 handling?
4. What is documented CLK sampling edge for wishbone_slave_interface monitor and reset sampling relative to CLK given fixed period P_fixed per test?

## Essential blockers


## Specification evidence

- `f_bus_8` → `/sections/10/entries/5` / `CH-d62a4ba2db`
> It has an 8-bit data bus for compatibility reason.

- `f_rbr_0` → `/sections/9/entries/0` / `CH-f88915355b`
> Receiver Buffer 0 8 R Receiver FIFO output

- `f_thr_0` → `/sections/9/entries/0` / `CH-f88915355b`
> 0 8 W Transmit FIFO input

- `f_ier_1` → `/sections/9/entries/0` / `CH-f88915355b`
> Interrupt Enable 1 8 RW Enable/Mask interrupts

- `f_iir_2` → `/sections/9/entries/0` / `CH-f88915355b`
> Interrupt Identification 2 8 R Get interrupt information

- `f_fcr_2` → `/sections/9/entries/0` / `CH-f88915355b`
> FIFO Control 2 8 W Control FIFO options

- `f_lcr_3` → `/sections/9/entries/0` / `CH-f88915355b`
> Line Control Register 3 8 RW Control connection

- `f_mcr_4` → `/sections/9/entries/0` / `CH-f88915355b`
> Modem Control 4 8 W Controls modem

- `f_lsr_5` → `/sections/9/entries/0` / `CH-f88915355b`
> Line Status 5 8 R Status information

- `f_msr_6` → `/sections/9/entries/0` / `CH-f88915355b`
> Modem Status 6 8 R Modem Status

- `f_dlab_set` → `/sections/9/entries/5` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set

- `f_dlab_block` → `/sections/9/entries/5` / `CH-f88915355b`
> the above registers at addresses 0-1

- `f_dll_0` → `/sections/9/entries/5` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor

- `f_dlm_1` → `/sections/9/entries/5` / `CH-f88915355b`
> Divisor Latch Byte 2 1 8 RW The MSB of the divisor
