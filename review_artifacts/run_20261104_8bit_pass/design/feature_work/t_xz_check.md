# X/Z protocol check

Work package: `t_xz_check` · checks · NEEDS_REVIEW

## Dependent features

- `t_chip_reset`: known non-XZ after deassertion needs reset bring-up first
- `t_wb_mon`: X-Z check needs sampled control-data monitors

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_init_cfg`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Monitor-level X/Z protocol check: error on X/Z sampled on WISHBONE serial modem and interrupt signals plus reset-known non-X/Z check after wb_rst_i deassertion; depends on reset bring-up and transaction monitors; uses RTL port names for code and spec references for behavior.

## Preconditions

1. Clock on wb_clk_i stable at symbolic P_fixed before any reset or sampling
2. Reset on wb_rst_i asserted to symbolic RST_ACTIVE then deasserted before configuration as first test step
3. Monitors for wishbone_slave_interface uart_serial_data modem_control_if and interrupt_output active through reset until test end
4. All DUT inputs owned to avoid testbench Z: wishbone_slave_interface drives wb_adr_i wb_dat_i wb_sel_i wb_we_i wb_stb_i wb_cyc_i and uart_serial_data drives srx_pad_i and modem_control_if drives cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i; clock and reset driven by testbench

## Stimulus pseudocode

```text
1. START clock on wb_clk_i with period P_fixed; HOLD fixed for test
2. ASSERT reset on wb_rst_i to RST_ACTIVE
3. WAIT symbolic reset duration scaled to P_fixed
4. DEASSERT reset on wb_rst_i to inactive level
5. WAIT symbolic settle cycles for DUT outputs to reach known values
6. DRIVE idle known values on wb_adr_i wb_dat_i wb_sel_i wb_we_i wb_stb_i wb_cyc_i via wishbone_slave_interface and on srx_pad_i via uart_serial_data and on cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i via modem_control_if; HOLD through checks
```

## Check pseudocode

```text
1. SAMPLE on each observed clock edge wb_adr_i wb_sel_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_clk_i wb_rst_i int_o stx_pad_o srx_pad_i rts_pad_o dtr_pad_o cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i [f_wb_addr_1 f_wb_sel_1 f_wb_data_1 f_wb_hs_1 f_int_o_1]; IF any sampled value is X or Z THEN REPORT uvm_error
2. WAIT for reset deassertion on wb_rst_i [f_wb_rst_1]; SAMPLE wb_dat_o wb_ack_o int_o stx_pad_o rts_pad_o dtr_pad_o; IF any is X or Z THEN REPORT error ELSE RECORD known-check pass
3. COMPARE reset-known state [f_init_fifo_1 f_init_shift_1 f_init_div_1 f_init_lcr_1 f_init_ier_1 f_mcr_rst_1]: IF Divisor Latch != 0 THEN REPORT error; IF LCR != 8-bits no-parity 1-stop THEN REPORT error; IF any IER interrupt enabled THEN REPORT error; IF FIFOs or shift registers not cleared THEN REPORT error
```

## Coverage pseudocode

```text
1. SAMPLE cover_xz_activation on each monitor sample of control and data
2. SAMPLE cover_xz_error on each X-or-Z error report
3. SAMPLE cover_known_after_reset when DUT outputs sampled known non-X/Z after reset deassertion
4. TAP monitor analysis ports with dedicated subscribers; drivers never supply coverage
```

## Completion

1. END when reset assertion plus deassertion plus settle window sampled and at least one known-value COMPARE observed
2. BOUND by TEST_TIMEOUT_CYCLES operational limit; timeout is testbench limit not DUT timing

## Questions

1. What signals are in documented known-value set after reset for X/Z checking beyond FIFOs and shift registers cleared, Divisor 0, LCR 8N1, IER disabled — specifically expected non-X/Z levels for wb_dat_o wb_ack_o int_o stx_pad_o rts_pad_o dtr_pad_o?
2. What is documented active polarity and inactive level of WB_RST_I on wb_rst_i? Source states only Asynchronous Reset.
3. What is documented minimum assert duration in clock cycles for WB_RST_I and required deassert-to-configuration delay and post-deassert settle for known check?
4. What is documented nominal clock period P_fixed and operating range for wb_clk_i?
5. What is documented CLK sampling edge for X/Z monitors and reset sampling relative to CLK?
6. Does X/Z error apply during reset assertion or only after deassertion, and must testbench drive all inputs to avoid Z during reset?
7. What are documented pad levels after MCR Reset Value 0 given inverted DTR and RTS mapping?

## Essential blockers


## Specification evidence

- `f_clk_1` → `/sections/4/strategy/agents/2` / `CH-63ad4d61a5`
> CLK 1 Input

- `f_wb_rst_1` → `/sections/4/strategy/agents/2` / `CH-63ad4d61a5`
> WB_RST_I 1 Input Asynchronous Reset

- `f_wb_addr_1` → `/sections/4/strategy/agents/2` / `CH-63ad4d61a5`
> WB_ADDR_I 5 or 3 Input Used for register selection

- `f_wb_sel_1` → `/sections/4/strategy/agents/2` / `CH-63ad4d61a5`
> WB_SEL_I 4 Input Select signal

- `f_wb_data_1` → `/sections/4/strategy/agents/2` / `CH-63ad4d61a5`
> WB_DAT_I 32 or 8 Input Data input
> WB_DAT_O 32 or 8 Output Data output

- `f_wb_hs_1` → `/sections/4/strategy/agents/2` / `CH-63ad4d61a5`
> WB_WE_I 1 Input Write or read cycle selection
> WB_STB_I 1 Input Specifies transfer cycle
> WB_CYC_I 1 Input A bus cycle is in progress
> WB_ACK_O 1 Output Acknowledge of a transfer

- `f_init_fifo_1` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The receiver and transmitter FIFOs are cleared.

- `f_init_shift_1` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The receiver and transmitter shift registers are cleared

- `f_init_div_1` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The Divisor Latch register is set to 0.

- `f_init_lcr_1` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The Line Control Register is set to communication of 8 bits of data, no parity, 1
> stop bit.

- `f_init_ier_1` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> All interrupts are disabled in the Interrupt Enable Register.

- `f_mcr_rst_1` → `/registers/registers/8/fields/0` / `CH-6abe65aeff`
> Reset Value: 0

- `f_int_o_1` → `/interfaces/groups/6/property_evidence/function` / `CH-8c2c8e9408`
> INT_O 1 Output Interrupt output
