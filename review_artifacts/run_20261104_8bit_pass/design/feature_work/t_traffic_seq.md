# Normal and loopback traffic sequences

Work package: `t_traffic_seq` · verification_plan · NEEDS_REVIEW

## Dependent features

- `t_wb_init_cfg`: normal and loopback payload reuse divisor line-format FIFO init base

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_reset_state`, `t_uart_mon`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Coordinate normal_traffic with wishbone payload plus uart TX RX plus modem toggles under IER-gated interrupt observe, and loopback_traffic by programming MCR Loopback 1 for internal TX-shift to RX-shift with documented modem remapping, reusing t_wb_init_cfg divisor line FIFO IER base with DLAB 0.

## Preconditions

1. WAIT for clock running at fixed period per test and reset released
2. REQUIRE t_wb_init_cfg_init_seq DONE with LCR DLAB 0 so normal registers accessible and wishbone bus idle-owned for handoff
3. REQUIRE symbolic bring-up divisor plus line-format plus FIFO trigger plus IER enables programmed; IER enables use symbolic SYM_IER with documented bits 3-0 polarity
4. REQUIRE MCR Loopback starting at normal 0; use symbolic SYM_PAYLOAD and SYM_MODEM_LEVELS without inventing bus values

## Stimulus pseudocode

```text
1. STAGE normal_directed: SPAWN virtual normal_traffic_sequence that spawns only; wishbone_slave_interface spawns wishbone payload moves owning wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i, uart_serial_data spawns RX drives owning srx_pad_i and observes stx_pad_o, modem_control_if spawns handshake toggles owning cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i and observes rts_pad_o dtr_pad_o, interrupt_output observes int_o
2. FOR each SYM_BURST with SYM_LEN: wishbone_slave_interface WRITE symbolic THR payload bytes; uart_serial_data DRIVE symbolic srx_pad_i frames with SYM_LINE matching LCR; modem_control_if DRIVE symbolic handshake levels; WAIT for wb_ack_o then wishbone_slave_interface READ symbolic RBR; observe stx_pad_o and int_o
3. STAGE loopback_directed: wishbone_slave_interface WRITE MCR Loopback 1 using symbolic MCR address; WAIT for idle; FOR each SYM_LOOP_BYTES: wishbone_slave_interface WRITE symbolic THR payload; WAIT for internal TX-to-RX transfer; wishbone_slave_interface READ symbolic RBR; modem_control_if OBSERVE remapped levels; interrupt_output OBSERVE int_o
4. STAGE random: FOR seed-controlled iterations: wishbone_slave_interface RANDOMIZE payload bytes with corner bias all-zeros all-ones within documented IER and MCR legal values 0 1; uart_serial_data RANDOMIZE gaps and TX versus RX interleave; modem_control_if RANDOMIZE handshake timing; IF Loopback equals 1 THEN constrain to internal transfer ELSE drive external serial
```

## Check pseudocode

```text
1. COMPARE loopback TX queue versus RX queue in order filtered by origin and address excluding configuration writes; PASS when order preserved without loss duplication or misorder
2. COMPARE stx_pad_o equals 1 WHILE MCR Loopback equals 1
3. COMPARE IER readback versus programmed enables for bits 3-0 with reserved 7-4 as 0
```

## Coverage pseudocode

```text
1. SAMPLE modem routing normal versus loopback via modem_control_if monitor tap on RTS_PAD_O DTR_PAD_O CTS_PAD_I DSR_PAD_I RI_PAD_I DCD_PAD_I plus MCR Loopback value
2. SAMPLE interrupt enables via wishbone_slave_interface monitor tap on IER bits 3-0 values
3. SAMPLE payload bytes with corner bias all-zeros all-ones via wishbone_slave_interface monitor tap and uart_serial_data monitor tap on TX versus RX
```

## Completion

1. Done when directed normal burst plus directed loopback burst plus bounded random bursts all ACKed with queues COMPAREd and coverage SAMPLEd
2. Bound by TEST_TIMEOUT_CYCLES operational limit; timeout is testbench limit not DUT timing
3. Cleanup: program MCR Loopback to 0 for normal, leave LCR DLAB 0 with wishbone bus idle-owned for handoff

## Questions

1. What are actual wb_adr_i pin values for THR RBR IER MCR FCR LCR under DLAB 0 versus divisor under DLAB 1 plus wb_sel_i handling and reset release to first write delay?
2. What symbolic divisor LSB MSB nonzero values plus LCR line-format values and FIFO trigger level and IER bits 3-0 combination bound normal versus loopback bring-up and traffic?
3. What uart_serial_data data_bits parity stop_bits bit_cycles settings must agree with LCR programming and divisor baud for TX observe and RX drive?
4. What Out1 Out2 control applies in normal operation outside loopback and what exact loopback data path beyond documented TX-shift to RX-shift plus DTR to DSR RTS to CTS Out1 to RI Out2 to DCD with STX held at 1 must be compared?
5. What documented interrupt observe mapping binds Received Data THRE Line Status Modem Status to normal versus loopback traffic and what overrun parity framing Data Ready order preservation without loss duplication applies?

## Essential blockers


## Specification evidence

- `f_ier_rda` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 0 RW Received Data available interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled

- `f_ier_thre` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 1 RW Transmitter Holding Register empty interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled

- `f_ier_lsi` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 2 RW Receiver Line Status Interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled

- `f_ier_msi` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 3 RW Modem Status Interrupt
>  ‘0’ – disabled
>  ‘1’ – enabled

- `f_mcr_loopback` → `/sections/4/strategy/agents/5` / `CH-6abe65aeff`
> 4 W Loopback mode
>  ‘0’ – normal operation
>  ‘1’ – loopback mode. When in loopback mode, the Serial
> Output Signal (STX_PAD_O) is set to logic ‘1’. The signal of the
> transmitter shift register is internally connected to the input of the
> receiver shift register.

- `f_mcr_map` → `/sections/4/strategy/agents/5` / `CH-6abe65aeff`
> The following connections are made:
> DTR Î  DSR
> RTS Î CTS
> Out1 Î RI
> Out2 Î DCD

- `f_mcr_dtr_rts` → `/sections/4/strategy/agents/5` / `CH-6abe65aeff`
> 0 W Data Terminal Ready (DTR) signal control
>  ‘0’ – DTR is ‘1’
>  ‘1’ – DTR is ‘0’
> 1 W Request To Send (RTS) signal control
>  ‘0’ – RTS is ‘1’
>  ‘1’ – RTS is ‘0’

- `f_lcr_dlab` → `/sections/12/entries/5` / `CH-bc7559f2ec`
> 7 RW Divisor Latch Access bit.
>  ‘1’ – The divisor latches can be accessed
>  ‘0’ – The normal registers are accessed
