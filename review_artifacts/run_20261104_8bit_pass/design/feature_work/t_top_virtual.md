# Top virtual and normal traffic control

Work package: `t_top_virtual` · stimulus · NEEDS_REVIEW

## Dependent features

- `t_wb_top_seq`: top spawn needs shared WISHBONE sequencer configuration
- `t_traffic_seq`: top normal-traffic coordination needs shared traffic sequencer configuration
- `t_clk_seq`: top spawn needs shared fixed-period clock sequencer configuration
- `t_chip_reset`: top spawn needs shared reset sequencer configuration

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_uart_mon`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Top virtual spawn-only coordination across wishbone_slave_interface uart_serial_data modem_control_if interrupt_output with common clock and reset plus normal-traffic WISHBONE payload with serial TX RX and modem handshake in ordered stages with no VIFs or delays.

## Preconditions

1. Virtual sequencer container holds handles for wishbone_slave_interface and uart_serial_data and modem_control_if and interrupt_output plus clock and reset without hierarchical pathing and without p_sequencer lock-in
2. Clock period P_fixed symbolic fixed per test started before reset and held fixed through traffic
3. Reset on wb_rst_i asserted first before any bus activity with duration tracking P_fixed polarity symbolic
4. DUT input ownership: wb_clk_i by clock and wb_rst_i by reset and wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i by wishbone_slave_interface and srx_pad_i by uart_serial_data and cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i by modem_control_if; outputs wb_dat_o wb_ack_o int_o stx_pad_o rts_pad_o dtr_pad_o observed
5. Bindings use RTL names wb_clk_i wb_rst_i wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i int_o stx_pad_o srx_pad_i rts_pad_o dtr_pad_o cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i with UART_DATA_WIDTH 8 and UART_ADDR_WIDTH 3 and DATA_BUS_WIDTH_8
6. Virtual sequences start on null sequencer drive nothing directly touch no VIFs use no delays with handles passed explicitly to every spawn

## Stimulus pseudocode

```text
1. START clock on wb_clk_i with symbolic P_fixed and HOLD fixed through all stages
2. ASSERT reset on wb_rst_i then WAIT done then DEASSERT before any configuration with duration tracking P_fixed
3. FOR seed S SAMPLE spawn order uniformly under S with knobs for burst length and idle without VIFs or delays
4. STAGE 0 bring-up: SPAWN symbolic divisor line-format FIFO programming using wishbone_slave_interface only driving its own wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i
5. STAGE 1 normal-traffic: SPAWN concurrently wishbone_slave_interface payload plus uart_serial_data TX-observe and RX-drive on srx_pad_i stx_pad_o plus modem_control_if handshake toggle plus interrupt_output observe
6. Per-agent rule: wishbone_slave_interface drives only WISHBONE inputs and uart_serial_data drives only srx_pad_i and modem_control_if drives only cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i
7. EXECUTE stages in order with concurrent spawns inside a stage and ordered stages across bring-up then traffic then cleanup leaving bus idle-owned
```

## Check pseudocode

```text
1. IF int_o observed THEN COMPARE IIR contents for highest priority pending interrupt per f_iir_enable
2. COMPARE IIR Bit0 pending indication where 0 means pending and 1 means none per f_iir_bit0
```

## Coverage pseudocode

```text
```

## Completion

1. Done when clock started before reset and held fixed through stages plus bring-up spawn plus normal-traffic spawns all finished with at least one scoreboard COMPARE observed
2. Bound by TEST_TIMEOUT_CYCLES operational limit; timeout is testbench limit not DUT timing
3. Cleanup virtual only with no VIFs or delays and bus left idle-owned for handoff

## Questions

1. What is documented bring-up order for reset, divisor, line format and FIFO that virtual stages must enforce?
2. What is documented active and inactive polarity of wb_rst_i plus minimum assert duration in clock cycles and deassert to first write delay with duration tracking P_fixed?
3. What is documented nominal clock period P_fixed and permitted bands for 3.6864 and 1258Mhz points plus duty jitter tolerance and is dynamic period change permitted?
4. What are documented legal masks access types and values per WISHBONE address including DLAB gating and wb_sel_i handling and wb_adr_i pin representation 3-bit versus 5-bit and addr 7 handling for 8-bit FIFO-only use?
5. What uart_serial_data data_bits parity stop_bits bit_cycles settings must agree with LCR programming and divisor baud for TX observe and RX drive?
6. What documented modem Out1 Out2 behavior applies in normal operation and what interrupt mapping binds Receiver Data THRE Line Status Modem Status to normal traffic with order preservation without loss duplication?
7. What symbolic divisor LSB MSB nonzero values plus LCR line values plus FIFO trigger plus IER bits bound normal bring-up when legal divisor range is unresolved?

## Essential blockers


## Specification evidence

- `f_core_8bit` → `/sections/4/strategy/agents/4` / `CH-d62a4ba2db`
> It has an 8-bit data bus for compatibility reason.

- `f_serial_pads` → `/sections/4/strategy/agents/4` / `CH-d62a4ba2db`
> It requires 2 pads in the chip (serial in and serial out)

- `f_iir_enable` → `/sections/8/entries/4` / `CH-f91cbf1c05`
> The IIR enables the programmer to retrieve what is the current highest priority pending

- `f_iir_bit0` → `/sections/8/entries/4` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’.
