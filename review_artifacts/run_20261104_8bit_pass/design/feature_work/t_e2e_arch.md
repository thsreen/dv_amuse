# End-to-end and architecture scoreboard

Work package: `t_e2e_arch` · checks · NEEDS_REVIEW

## Dependent features

- `t_traffic_seq`: end-to-end integrity needs normal and loopback traffic stimulus
- `t_uart_mon`: end-to-end compare needs serial byte queues

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Top-level scoreboard infrastructure traces WISHBONE THR writes to stx_pad_o TX to srx_pad_i RX to RBR reads plus architecture pending-request liveness; documented reset init serial-direction and IIR-pending bound checks; byte order preservation FIFO depth overrun handling and timeout values lack documented source and stay gated by questions so payload equality is collection-only until answered

## Preconditions

1. Reset driven on reset with clock fixed per test; FIFOs and shift registers cleared Divisor 0 LCR 8N1 interrupts disabled [f_reset_1 f_reset_2]
2. Init programming done with symbolic divisor LCR FIFO trigger IER using DLAB gating MSB first and baud formula with serial settings agreeing [f_init_1 f_init_2]
3. Agents own inputs: wishbone_slave_interface owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i, uart_serial_data owns srx_pad_i and observes stx_pad_o srx_pad_i, modem_control_if owns cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i, interrupt_output observes int_o [f_serial_1 f_arch_1 f_modem_1]
4. Traffic stimulus available from t_traffic_seq normal and loopback bursts and byte monitors from t_uart_mon with symbolic bus pin addresses and symbolic line format

## Stimulus pseudocode

```text
1. WAIT reset deassertion THEN WAIT init_config completion with symbolic divisor LCR FIFO trigger IER before enabling scoreboard queues
2. WAIT normal_traffic burst with wishbone payload writes plus uart TX observe plus uart RX drive plus modem toggles under IER observe
3. WAIT loopback_traffic burst with internal TX to RX routing using symbolic loopback control
```

## Check pseudocode

```text
1. WAIT reset deassertion THEN SAMPLE symbolic divisor LCR IER reads AND COMPARE to f_reset_1 f_reset_2 for cleared FIFOs Divisor 0 LCR 8N1 interrupts disabled
2. SAMPLE wishbone_slave_interface monitor completed STB CYC to ACK transactions into wb_req_queue and wb_ack_queue; FOR each request TRACK pending UNTIL ACK OR request_timeout_cycles operational limit THEN REPORT unanswered as liveness event [f_arch_1]
3. SAMPLE THR payload writes filtered by origin address excluding configuration writes into exp_queue AND SAMPLE stx_pad_o TX bytes as DUT output into tx_queue AND SAMPLE srx_pad_i RX bytes as DUT input into rx_queue AND SAMPLE RBR payload reads into act_queue [f_serial_1 f_arch_1]
4. COMPARE queue counts for loss duplication as infrastructure tally; IF overrun-free documented condition THEN COMPARE exp_queue vs tx_queue vs rx_queue vs act_queue in order ELSE REPORT overrun-pending without oracle; never COMPARE an event with itself
5. SAMPLE interrupt_output monitor INT_O AND SAMPLE IIR bit0 via symbolic reads AND COMPARE pending rule 0 equals pending asserted 1 equals idle negated subject to IER enables [f_iir_1 f_modem_1]
6. WAIT drain_cycles operational limit for pipeline flush THEN REPORT all queues and pending counts; CLEANUP disable queues and leave wishbone bus and srx_pad_i idle-owned for handoff
```

## Coverage pseudocode

```text
```

## Completion

1. Done when reset values COMPAREd plus normal and loopback bursts drained with queue tallies REPORTED and IIR pending COMPARE observed or TEST_TIMEOUT_CYCLES expires
2. Bound by drain_cycles and request_timeout_cycles as TESTBENCH operational limits not DUT timing
3. Cleanup disables scoreboard queues leaves DLAB 0 symbolic wishbone bus idle-owned and srx_pad_i idle-owned by uart_serial_data

## Questions

1. What documented FIFO depth and ordering guarantees define expected end-to-end queues for loss duplication misorder beyond allowed overrun?
2. What testbench drain_cycles and request_timeout_cycles operational limits detect deadlock livelock without assuming DUT timing?
3. What are actual wb_adr_i pin values for THR RBR IER FCR LCR under DLAB 0 versus divisor under DLAB 1 plus wb_sel_i handling under DATA_BUS_WIDTH_8?
4. What symbolic divisor LSB MSB nonzero values plus LCR line-format values plus FIFO trigger level plus IER bits bound normal versus loopback bring-up?
5. What uart_serial_data data_bits parity stop_bits bit_cycles settings must agree with LCR programming and divisor baud for TX observe and RX drive?
6. What is wb_rst_i polarity and required deassert to first write delay with clock period fixed per test?
7. What documented loopback data path and modem remapping defines expected routing for loopback compare versus normal STX to SRX wiring?

## Essential blockers


## Specification evidence

- `f_reset_1` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The receiver and transmitter FIFOs are cleared.

- `f_reset_2` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The Line Control Register is set to communication of 8 bits of data, no parity, 1
> stop bit.

- `f_init_1` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> Set the Divisor Latches, MSB first, LSB next.

- `f_init_2` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> Remember that (Input Clock Speed)/(Divisor Latch value) = 16 x the communication
> baud rate.

- `f_serial_1` → `/interfaces/groups/4/property_evidence/function` / `CH-98be4510fb`
> STX_PAD_O 1 Output The serial output signal
> SRX_PAD_I 1 Input The serial input signal

- `f_arch_1` → `/sections/4/strategy/agents/4` / `CH-d62a4ba2db`
> It has an 8-bit data bus for compatibility reason.

- `f_iir_1` → `/sections/8/entries/3` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’. When it’s ‘1’ – no interrupt
> is pending.

- `f_modem_1` → `/sections/8/entries/10` / `CH-f91cbf1c05`
> 0 0 0 4 th Modem Status CTS, DSR, RI or DCD.
