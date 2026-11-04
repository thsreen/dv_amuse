# Collated implementation understanding

Dependency analysis orders fixed-period clock then chip reset then WISHBONE init config then top stimulus and normal-loopback traffic, with WISHBONE UART interrupt-baud monitors before DLAB interrupt LSR reset-state X-Z scoreboard checks and coverage, and top virtual spawning via shared sequencer config.

## t_clk_seq

Fixed-period clock stimulus drives RTL wb_clk_i spec CLK with one symbolic period P_fixed per test started before reset and held through traffic with observed-edge sampling for band boundary stratum once documented WISHBONE points bands defined

[Detailed pseudocode](t_clk_seq.md)

## t_chip_reset

Chip reset bring-up starts stable fixed-period clock on wb_clk_i before asserting asynchronous reset on wb_rst_i as first step before any configuration, tracking duration to symbolic P_fixed; quick-test-only active-high 10-cycle hold is testbench choice not documented DUT requirement.

[Detailed pseudocode](t_chip_reset.md)

## t_clk_cov

Clock period coverage samples observed wb_clk_i spec CLK edges with one symbolic fixed period P_fixed per test started before reset and held through traffic; raw period sampling is supported, band boundary stratum classification deferred until documented bands defined with no invented bounds or dynamic switching.

[Detailed pseudocode](t_clk_cov.md)

## t_irq_baud_mon

Build passive INT_O observation via interrupt_output agent timestamped on fixed-period clock without driving; optional 16x baud-tick observation pending physical binding and documented period mapping; reset clears pending state and restarts measurement.

[Detailed pseudocode](t_irq_baud_mon.md)

## t_wb_mon

Build wishbone_slave_interface monitor sampling RTL pins wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i on observed CLK edges from fixed-period clock, reconstructing completed read and write transactions on WB_ACK_O assertion for analysis port, flushing in-flight on wb_rst_i, with X or Z and known-after-reset checks and ACK-sampled register and DLAB coverage for 8-bit addresses 0-6.

[Detailed pseudocode](t_wb_mon.md)

## t_irq_id_cov

Cover IIR bit0 pending flag, bits3-1 priority codes for five sources, and fixed compatibility bits sampled on IIR reads.

[Detailed pseudocode](t_irq_id_cov.md)

## t_reset_state

After global reset top-level scoreboard reconstructs idle WISHBONE reads on observed wb_clk_i edges to check receiver/transmitter FIFOs and shift registers cleared, Divisor Latch 0, LCR 8N1, and IER interrupts disabled, depending on chip-reset bring-up and wishbone monitor.

[Detailed pseudocode](t_reset_state.md)

## t_wb_init_cfg

Directed init_config_sequence on wishbone_slave_interface_agent after chip_reset: set LCR DLAB 1, program Divisor MSB first LSB next, clear DLAB 0, then program FIFO trigger and IER enables using only documented addresses order and enable polarity with symbolic bring-up values.

[Detailed pseudocode](t_wb_init_cfg.md)

## t_wb_reg_cov

Cover WISHBONE slave accesses at bus pin values 0-6 with read/write direction and byte data classes and documented per-address access types, sampled from completed transactions with DLAB 0 for normal registers.

[Detailed pseudocode](t_wb_reg_cov.md)

## t_wb_scoreboard

WISHBONE agent scoreboard inside wishbone_slave_interface agent tracks monitor-reported completed transactions to detect lost duplicated or misordered transfers with read-data comparison only where documented reference exists; eventually-answered uses testbench timeout not documented DUT bound provenance INFERRED quick-test only.

[Detailed pseudocode](t_wb_scoreboard.md)

## t_xz_check

Monitor-level X/Z protocol check: error on X/Z sampled on WISHBONE serial modem and interrupt signals plus reset-known non-X/Z check after wb_rst_i deassertion; depends on reset bring-up and transaction monitors; uses RTL port names for code and spec references for behavior.

[Detailed pseudocode](t_xz_check.md)

## t_divisor_cov

Cover DLAB-gated divisor latch programming with LSB MSB zero max and combined value bins sampled on Wishbone write completions with DLAB 1.

[Detailed pseudocode](t_divisor_cov.md)

## t_dlab_gate_chk

Verify DLAB gating on wishbone_slave_interface with RTL ports wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i using pin values 0 1 3: divisor LSB and MSB at 0 and 1 accessible only when LCR bit7 is 1 and normal at 0 and 1 only when 0 with alias-toggle reads and RW compares at addr1 plus cross coverage; depends on monitor reconstruction and init divisor then clear programming; QUICK_TEST_PLAN_APPROVAL intentions stay INFERRED and spec-to-RTL map is reused with only DOCUMENTED facts constraining behavior.

[Detailed pseudocode](t_dlab_gate_chk.md)

## t_traffic_seq

Coordinate normal_traffic with wishbone payload plus uart TX RX plus modem toggles under IER-gated interrupt observe, and loopback_traffic by programming MCR Loopback 1 for internal TX-shift to RX-shift with documented modem remapping, reusing t_wb_init_cfg divisor line FIFO IER base with DLAB 0.

[Detailed pseudocode](t_traffic_seq.md)

## t_uart_mon

Build uart_serial_data monitor observing stx_pad_o and driving srx_pad_i timing via programmed divisor to reconstruct TX RX bytes with framing break attributes, after wishbone divisor bring-up, using symbolic line format pending source confirmation

[Detailed pseudocode](t_uart_mon.md)

## t_wb_top_seq

WISHBONE top sequence on wishbone_slave_interface_agent drives controlled register reads and writes within documented addresses 0-6 with DLAB gating, reusing init DLAB base; clock fixed per test, coverage sampled on completion.

[Detailed pseudocode](t_wb_top_seq.md)

## t_addr_dlab_cov

Cover WISHBONE pin address crossed with LCR DLAB gating for divisor versus normal aliasing at 0-1 plus normal 2-6 and illegal 7 sampled on ACK completion via wishbone_slave_interface monitor.

[Detailed pseudocode](t_addr_dlab_cov.md)

## t_e2e_arch

Top-level scoreboard infrastructure traces WISHBONE THR writes to stx_pad_o TX to srx_pad_i RX to RBR reads plus architecture pending-request liveness; documented reset init serial-direction and IIR-pending bound checks; byte order preservation FIFO depth overrun handling and timeout values lack documented source and stay gated by questions so payload equality is collection-only until answered

[Detailed pseudocode](t_e2e_arch.md)

## t_ier_iir_pend

Verify IER bits 0-3 enable Received-Data THRE Receiver-Line-Status Modem-Status with 0 disabled 1 enabled via readback, and IIR bit0 0 pending 1 none correlated with passive int_o when enabled.

[Detailed pseudocode](t_ier_iir_pend.md)

## t_line_err_cov

Deferred (quick testing): code_feature: work package too large; split this package

[Detailed pseudocode](t_line_err_cov.md)

## t_lsr_status

Deferred (quick testing): code_feature: work package too large; split this package

[Detailed pseudocode](t_lsr_status.md)

## t_modem_irq

Verify modem status interrupt where CTS DSR RI DCD toggles set MSR deltas cleared by MSR read and assert INT_O with IIR Modem Status only when IER bit3 enabled checked in modem agent and top scoreboard in normal mode with DLAB 0

[Detailed pseudocode](t_modem_irq.md)

## t_top_virtual

Deferred (quick testing): code_feature: work package too large; split this package

[Detailed pseudocode](t_top_virtual.md)

## t_iir_prio_fixed

Deferred (quick testing): code_feature: work package too large; split this package

[Detailed pseudocode](t_iir_prio_fixed.md)

## t_irq_err_chk

Deferred (quick testing): code_feature: work package too large; split this package

[Detailed pseudocode](t_irq_err_chk.md)

## t_modem_traffic_cov

Cover single-instance cross of Modem Status IIR 000 from CTS DSR RI DCD with concurrent serial traffic states idle tx_active rx_active tx_rx_active plus no_modem traffic sampled on IIR indication on clock edges during data flow

[Detailed pseudocode](t_modem_traffic_cov.md)