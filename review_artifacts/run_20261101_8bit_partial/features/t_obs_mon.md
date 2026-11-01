# Modem interrupt baud observers

Work package: `t_obs_mon` · monitor · NEEDS_REVIEW

## Dependent features

- `t_bringup_clk`: Passive modem interrupt baud observers require stable clock and reset order before status comparison.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_uart_cfg`, `t_wb_acc_cov`, `t_wb_mon`, `t_wb_seq`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Implement passive observers for modem_control_if on rts_pad_o dtr_pad_o cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and uart_interrupt on int_o with analysis ports for status and interrupt comparison after bring-up clock and reset order. baud_output has no RTL port and no agent and is retained as unsupported without driving or sampling.

## Preconditions

1. WAIT for clock stable at SYM_CLK_PERIOD and reset deasserted plus SYM_IDLE_CYCLES before enabling observers
2. ASSUME wishbone_bus owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i and observes wb_dat_o wb_ack_o
3. ASSUME serial_data owns srx_pad_i and observes stx_pad_o
4. ASSUME modem_control_if owns cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and observers tap rts_pad_o dtr_pad_o plus inputs passively
5. ASSUME uart_interrupt observes int_o passively and drives nothing
6. ASSUME monitors drive no DUT inputs and provide analysis ports for scoreboard plumbing

## Stimulus pseudocode

```text
```

## Check pseudocode

```text
1. SAMPLE rts_pad_o dtr_pad_o cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i on clock and PUBLISH modem_status_event to analysis port without driving
2. SAMPLE int_o level on clock and on transition PUBLISH interrupt_event to analysis port without driving
3. IF reset asserted THEN FLUSH partial modem and interrupt events and WAIT for deassertion plus SYM_IDLE_CYCLES before resuming SAMPLE
4. COMPARE observed int_o level against IIR bit0 value from wishbone_bus read to qualify pending versus no-pending
5. CHECK observed int_o assertion only when corresponding IER bit among 0-3 is enabled as programmed via wishbone_bus
```

## Coverage pseudocode

```text
1. SAMPLE cg_interrupt from uart_interrupt analysis port covering IIR pending versus no-pending and IER bits 0-3 combinations including all-disabled
2. SAMPLE cg_modem from modem_control_if analysis port covering each pin toggle and combined status change
```

## Completion

1. WAIT for modem and interrupt event queues to drain within TEST_TIMEOUT_CYCLES operational limit not DUT timing
2. CLEANUP release observer handles and leave DUT pins to owners with monitors driving nothing

## Questions

1. Confirm modem interrupt and baud observation ports and passive roles including analysis port destinations?
2. Where is BAUD_O physical port and binding given interface has no BAUD_O and existing agents have no baud_output?
3. How do rts_pad_o dtr_pad_o map to MCR and cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i map to MSR status and delta including loopback routing for comparison?
4. How does each IER enable bit gate INT_O assertion priority and clearing including which wishbone_bus register access clears each RDA THRE line-status modem-status source?
5. What clock edge and synchronization depth must modem and interrupt monitors use and how must they flush on reset given wb_rst_i polarity duration sequencing unresolved?
6. What are idle tie-off levels for modem inputs when modem_control_if inactive and required post-reset idle checks before observation?

## Essential blockers


## Specification evidence

- `f_ier_enable` → `/sections/8/entries/4` / `CH-de51b2eafc`
> This register allows enabling and disabling interrupt generation by the UART.

- `f_ier_bit0` → `/sections/8/entries/4` / `CH-de51b2eafc`
> 0 RW Received Data available interrupt

- `f_ier_bit1` → `/sections/8/entries/4` / `CH-de51b2eafc`
> 1 RW Transmitter Holding Register empty interrupt

- `f_ier_bit2` → `/sections/8/entries/4` / `CH-de51b2eafc`
> 2 RW Receiver Line Status Interrupt

- `f_ier_bit3` → `/sections/8/entries/4` / `CH-de51b2eafc`
> 3 RW Modem Status Interrupt

- `f_iir_pending0` → `/sections/8/entries/5` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’.

- `f_iir_nopending1` → `/sections/8/entries/5` / `CH-f91cbf1c05`
> When it’s ‘1’ – no interrupt
