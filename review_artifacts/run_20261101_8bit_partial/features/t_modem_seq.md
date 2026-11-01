# Modem handshake sequences

Work package: `t_modem_seq` · sequence · NEEDS_REVIEW

## Dependent features

- None identified.

## Independent features

`t_bringup_clk`, `t_clk_cov`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_lsr_par_fram`, `t_obs_mon`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_uart_cfg`, `t_wb_acc_cov`, `t_wb_mon`, `t_wb_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Drive modem handshake via modem_control_if with directed single-pin toggles plus simultaneous toggles plus MCR DTR/RTS/Out1/Out2 and loopback entry-exit coordinated with wishbone_bus MCR programming.

## Preconditions

1. Clock is stable at selected period and reset is released to inactive without assuming polarity per q_reset.
2. modem_control_if agent is active and owns cts_pad_i plus dsr_pad_i plus ri_pad_i plus dcd_pad_i drives and observes rts_pad_o plus dtr_pad_o plus inputs.
3. wishbone_bus agent is available for symbolic MCR programming of DTR plus RTS plus Out1 plus Out2 plus loopback without assuming address per q_bus.
4. DUT starts in normal operation with symbolic MCR loopback cleared per f_loop_mode.

## Stimulus pseudocode

```text
1. FOR each pin in [cts_pad_i, dsr_pad_i, ri_pad_i, dcd_pad_i]: DRIVE single toggle to opposite level via modem_control_if; WAIT clock edge; SAMPLE monitor.
2. DRIVE constrained-random simultaneous toggles on a subset of inputs via modem_control_if; WAIT clock edge between interleavings; REPEAT with reproducible seed up to symbolic num_modem_events.
3. SET symbolic MCR loopback bit to 1 via wishbone_bus to enter loopback per f_loop_mode; WAIT clock edge.
4. WHILE in loopback: SET symbolic MCR DTR plus RTS plus Out1 plus Out2 via wishbone_bus per f_dtr_inv plus f_rts_inv plus f_out_map; OBSERVE routed equivalents via modem_control_if monitor without driving external inputs.
5. CLEAR symbolic MCR loopback bit to 0 via wishbone_bus to exit to normal per f_loop_mode; WAIT clock edge; RESUME external pin drives via modem_control_if.
6. IF external coordination needed: ORDER symbolic MCR programming on wishbone_bus before pin-drive bursts using events without virtual-interface delays.
```

## Check pseudocode

```text
1. COMPARE observed rts_pad_o against inverted MCR RTS control per f_rts_inv on clock edges via modem_control_if monitor.
2. COMPARE observed dtr_pad_o against inverted MCR DTR control per f_dtr_inv on clock edges via modem_control_if monitor.
3. COMPARE loopback active state: STX_PAD_O is logic 1 and transmitter shift output is internally connected to receiver shift input per f_loop_mode.
4. COMPARE loopback routing DTR to DSR and RTS to CTS and Out1 to RI and Out2 to DCD per f_loop_map while loopback active.
5. SAMPLE modem_control_if monitor observations on clock edges for check activation; no driver-supplied expected results.
```

## Coverage pseudocode

```text
1. SAMPLE cover for single-pin toggle on each of cts_pad_i and dsr_pad_i and ri_pad_i and dcd_pad_i.
2. SAMPLE cover for simultaneous-toggle combination with corner-biased multi-pin case.
3. SAMPLE cover for MCR DTR and RTS inversion values 0 and 1.
4. SAMPLE cover for loopback entry plus loopback-active with MCR controls plus loopback exit to normal.
```

## Completion

1. WAIT until all scheduled single toggles plus simultaneous toggles plus loopback entry-exit complete.
2. WAIT until modem_control_if monitor queue drains within TESTBENCH operational limit drain_cycles.
3. COMPARE all scheduled checks and FAIL on any mismatch; CLEANUP by clearing symbolic MCR loopback to normal and returning driven pins to idle level per q_idle.

## Questions

1. q_idle: What are the inactive and idle driven levels for cts_pad_i, dsr_pad_i, ri_pad_i and dcd_pad_i? Do not infer from names.
2. q_reset: What is wb_rst_i active polarity and what are rts_pad_o and dtr_pad_o levels during reset and does MCR clear per f_mcr_reset?
3. q_bus: What are the WISHBONE pin addresses and byte lanes and write masks for MCR controls and for any MSR observation?
4. q_mcr_read: What does a WISHBONE read of write-only MCR return?
5. q_msr: What are the required MSR current-state versus delta semantics including complement versus loopback equality and DCTS plus DDSR plus TERI plus DDCD set and clear on read for checks?
6. q_ier: What IER enable combination gates modem-status interrupt observation during modem toggles?
7. q_timing: What setup plus hold and minimum spacing apply to modem input toggles relative to clock edges?

## Essential blockers


## Specification evidence

- `f_modem_pins` → `/sections/10/entries/5` / `CH-d62a4ba2db`
> RTS_O
> CTS_I
> DTR_O
> DSR_I
> DCD_I
> RI_I

- `f_gpio_option` → `/sections/10/entries/5` / `CH-d62a4ba2db`
> and, optionally, another six modem
> control signals, which can otherwise be implemented using general purpose I/Os on the
> chip.

- `f_dtr_inv` → `/sections/12/entries/7` / `CH-6abe65aeff`
> 0 W Data Terminal Ready (DTR) signal control
>  ‘0’ – DTR is ‘1’
>  ‘1’ – DTR is ‘0’

- `f_rts_inv` → `/sections/12/entries/7` / `CH-6abe65aeff`
> 1 W Request To Send (RTS) signal control
>  ‘0’ – RTS is ‘1’
>  ‘1’ – RTS is ‘0’

- `f_out_map` → `/sections/12/entries/7` / `CH-6abe65aeff`
> 2 W Out1. In loopback mode, connected Ring Indicator (RI) signal input
> 3 W Out2. In loopback mode, connected to Data Carrier Detect (DCD)
> input.

- `f_loop_mode` → `/sections/12/entries/7` / `CH-6abe65aeff`
> 4 W Loopback mode
>  ‘0’ – normal operation
>  ‘1’ – loopback mode. When in loopback mode, the Serial
> Output Signal (STX_PAD_O) is set to logic ‘1’. The signal of the
> transmitter shift register is internally connected to the input of the
> receiver shift register.

- `f_loop_map` → `/sections/12/entries/7` / `CH-6abe65aeff`
> The following connections are made:
> DTR Î  DSR
> RTS Î CTS
> Out1 Î RI
> Out2 Î DCD

- `f_mcr_reset` → `/sections/12/entries/7` / `CH-6abe65aeff`
> 7-5 W Ignored
> Reset Value: 0
