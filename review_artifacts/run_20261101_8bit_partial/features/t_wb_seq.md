# Wishbone register access sequences

Work package: `t_wb_seq` · sequence · NEEDS_REVIEW

## Dependent features

- None identified.

## Independent features

`t_bringup_clk`, `t_clk_cov`, `t_ier_reset`, `t_iir_cov`, `t_modem_seq`, `t_obs_mon`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_wb_mon`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Implement wishbone_bus wishbone_reg_access base plus read/write and DLAB-gated divisor LSB MSB children for directed bring-up then constrained-random traffic in DATA_BUS_WIDTH_8 responder build. QUICK_TEST_PLAN_APPROVAL intentions are INFERRED temporary test-only approvals not engineer sign-off; reuse checked wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o map with RTL names for code and spec refs for behavior; keep partial supported DLAB routing even while SEL value reset polarity ACK timing and full masks await answers.

## Preconditions

1. DUT is DATA_BUS_WIDTH_8 build with 8-bit data and 3-bit wb_adr_i pin values 0 to 6; 5-bit form applies only to 32-bit mode [f_bus8_1] [f_adr_mode_1] [f_wb_addr_1] [f_wb_impl_1] [f_compat8_1]
2. Clock has fixed period per test and reset uses common reset with symbolic active level SYM_WB_RST_ACTIVE; reset polarity and handshake inactive levels are unresolved [f_wb_rst_1]
3. Power-on reset completed via reset; wishbone_reg_access runs after reset and coordinated with uart_config; LCR DLAB state held symbolically with set-then-clear order and MSB-first LSB-next divisor order [f_dlab_set_1] [f_dlab_clear_1] [f_div_order_1]
4. wishbone_bus active agent owns wb_adr_i and wb_dat_i and wb_we_i and wb_stb_i and wb_cyc_i and wb_sel_i and observes wb_dat_o and wb_ack_o; clock and reset are common; serial_data owns srx_pad_i and modem_control_if owns cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i; no other driver touches wishbone inputs [f_wb_we_1] [f_wb_stb_1] [f_wb_cyc_1] [f_wb_ack_1]
5. Bus address representation is explicit wb_adr_i pin value; wb_sel_i legal value in 8-bit mode is symbolic SYM_WB_SEL_8BIT pending answer; TESTBENCH request_timeout_cycles and drain_cycles are operational limits not DUT timing

## Stimulus pseudocode

```text
1. FOR directed bring-up in order: START wishbone_reg_access base on wishbone_bus sequencer with explicit handle; drive only wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i plus symbolic SYM_WB_SEL_8BIT; observe wb_ack_o and wb_dat_o [f_wb_addr_1]
2. IF SYM_DLAB equals 0 THEN FOR wb_adr_i in 2 to 6 plus shared 0 to 1 normal path: WRITE then READ with configured wb_dat_i; WAIT wb_ack_o on clock edge per transfer [f_rb_1] [f_thr_1]
3. IF SYM_DLAB equals 1 THEN WRITE divisor MSB at wb_adr_i 1 first THEN WRITE divisor LSB at wb_adr_i 0 next; then CLEAR DLAB via LCR at wb_adr_i 3 per set-then-clear order [f_dlab_gate_1] [f_dlsb_1] [f_dmsb_1] [f_div_order_1] [f_dlab_set_1] [f_dlab_clear_1]
4. FOR random top: REPEAT num_wb_trans times with reproducible seed: RANDOMLY SELECT among read child and write child and DLAB-gated divisor LSB MSB children; RANDOMIZE wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i within documented pin values plus symbolic SEL; enforce DLAB constraint for 0 to 1 alias [f_dlab_gate_1]
5. INSERT inter-transaction idle gap as TESTBENCH choice; virtual sequence SPAWNS children with explicit wishbone_bus sequencer handle only, drives no signals directly, uses no VIFs and no delays; handshake sampled on clock edges
```

## Check pseudocode

```text
1. WAIT wb_ack_o for each driven transfer on clock edge with TESTBENCH request_timeout_cycles as operational limit only; never treat timeout as DUT timing [f9]
2. SAMPLE completed write/read transaction from wishbone_bus monitor analysis port including wb_adr_i and wb_dat_i/wb_dat_o and DLAB state at access time [f6]
3. COMPARE observed routing only: IF DLAB set THEN wb_adr_i 0 maps to divisor LSB and wb_adr_i 1 maps to divisor MSB ELSE wb_adr_i 0 maps to Receiver Buffer/THR path [f3]
4. COMPARE queues of observed completed transactions filtered by origin and wb_adr_i pin value; exclude configuration writes from payload routes; never compare an event with itself
```

## Coverage pseudocode

```text
1. SAMPLE wb_adr_i pin value plus wb_we_i direction plus DLAB state on wb_ack_o via dedicated coverage subscriber tapping wishbone_bus monitor analysis port; driver never samples [f6]
2. COVER wb_adr_i 0 to 6 read versus write with DLAB 0 normal versus DLAB 1 divisor at shared 0 to 1 [f3]
3. COVER shared-address direction mapping sampled from monitor: read path versus write path at same pin value [f1]
```

## Completion

1. FOR num_wb_trans ACKs OR UNTIL TESTBENCH request_timeout_cycles expires: WAIT all spawned children complete
2. Deassert wb_stb_i and wb_cyc_i via wishbone_bus driver cleanup; leave other interfaces untouched
3. DRAIN wishbone_bus monitor for drain_cycles as TESTBENCH operational limit then close sequence

## Questions

1. Confirm address representation and DLAB gating for shared addresses before coding: are write/read addresses literal 3-bit wb_adr_i pin values 0 to 6 in DATA_BUS_WIDTH_8 build, what is legality of addr 7, and does DLAB 1 route addr 0 to divisor LSB and addr 1 to divisor MSB while blocking normal 0 to 1 with set-then-clear order?
2. What is active level of wb_rst_i and inactive levels of wb_stb_i wb_cyc_i wb_we_i, and what is legal wb_sel_i value to drive with 4-bit wb_sel_i and 8-bit data in DATA_BUS_WIDTH_8 build?
3. What is expected WB_ACK_O handshake behavior and operational request_timeout_cycles and back-to-back idle rule: single ACK per STB plus CYC, any maximum latency, and required idle between transfers?
4. What are constrained-random legal masks and values for WB_ADDR_I WB_DAT_I WB_WE_I WB_STB_I WB_CYC_I plus divisor LSB MSB and LCR IER FCR MCR knobs, and explicit comparison masks for any register-mirror checks given DLAB-banked fields?
5. What virtual-sequence coordination is required: explicit sequencer-handle passing, null-sequencer start, and ordering of power_on_reset then uart_config then wishbone traffic without VIFs or delays in virtual sequences?

## Essential blockers


## Specification evidence

- `f_rb_1` → `/sections/5/entries/0` / `CH-f88915355b`
> Receiver Buffer 0 8 R Receiver FIFO output

- `f_thr_1` → `/sections/5/entries/0` / `CH-f88915355b`
> 0 8 W Transmit FIFO input

- `f_dlab_gate_1` → `/sections/5/entries/0` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set
> to ‘1’. At this time the above registers at addresses 0-1 can’t be accessed.

- `f_dlsb_1` → `/sections/5/entries/0` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor
> latch

- `f_dmsb_1` → `/sections/5/entries/0` / `CH-f88915355b`
> Divisor Latch Byte 2 1 8 RW The MSB of the divisor
> latch

- `f_wb_addr_1` → `/sections/7/entries/0` / `CH-63ad4d61a5`
> WB_ADDR_I 5 or 3 Input Used for register selection

- `f_wb_we_1` → `/sections/7/entries/0` / `CH-63ad4d61a5`
> WB_WE_I 1 Input Write or read cycle selection

- `f_wb_stb_1` → `/sections/7/entries/0` / `CH-63ad4d61a5`
> WB_STB_I 1 Input Specifies transfer cycle

- `f_wb_cyc_1` → `/sections/7/entries/0` / `CH-63ad4d61a5`
> WB_CYC_I 1 Input A bus cycle is in progress

- `f_wb_ack_1` → `/sections/7/entries/0` / `CH-63ad4d61a5`
> WB_ACK_O 1 Output Acknowledge of a transfer

- `f_wb_rst_1` → `/sections/7/entries/0` / `CH-63ad4d61a5`
> WB_RST_I 1 Input Asynchronous Reset

- `f_div_order_1` → `/sections/5/entries/1` / `CH-1e2324cfc3`
> Set the Divisor Latches, MSB first, LSB next.

- `f_dlab_clear_1` → `/sections/5/entries/1` / `CH-1e2324cfc3`
> Set bit 7 of LCR to ‘0’ to disable access to Divisor Latches.

- `f_dlab_set_1` → `/sections/5/entries/1` / `CH-1e2324cfc3`
> Set bit 7 to ‘1’
> to allow access to the Divisor Latches.

- `f_adr_mode_1` → `/sections/4/strategy/agents/0/sequences/0` / `CH-419b99d7d8`
> Also, in 32-bit data bus mode, the [ADR_I] is 5 and not 3 bits wide.

- `f_bus8_1` → `/sections/4/strategy/agents/0/sequences/0` / `CH-419b99d7d8`
> DATA_BUS_WIDTH_8 in uart_defines.v, uart_top.v or on the compiler/synthesizer tool

- `f_wb_impl_1` → `/sections/4/strategy/agents/0` / `CH-d62a4ba2db`
> The core implements the WISNBONE SoC bus interface for communication with the
> system.

- `f_compat8_1` → `/sections/4/strategy/agents/0` / `CH-d62a4ba2db`
> It has an 8-bit data bus for compatibility reason.
