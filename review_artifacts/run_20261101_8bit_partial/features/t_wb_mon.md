# Wishbone bus monitor

Work package: `t_wb_mon` · monitor · NEEDS_REVIEW

## Dependent features

- `t_bringup_clk`: Wishbone handshake sampling requires stable clock and reset deassertion order to avoid X sampling.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_uart_cfg`, `t_wb_seq`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Implement passive wishbone_bus monitor for DATA_BUS_WIDTH_8 build sampling DUT responder WISHBONE signals on the clock with reset flushing and reconstructing read and write register transactions with address data control and ACK latency for predictor and scoreboard forwarding with no local compare. Depends on stable clock and ordered reset deassertion. DOCUMENTED sources define signal directions and bus interface role; handshake polarity, framing and ACK timing, address representation, SEL use, sampling edge and reset sequencing remain symbolic. Quick-test intentions guide architecture only and are not sign-off.

## Preconditions

1. WAIT for clock stable and reset deasserted via clock and reset coordination before enabling sampling [f_clk_1,f_rst_1]
2. ENTER passive observe-only mode driving no DUT inputs on SoC bus interface [f_bus_1]
3. FLUSH all queued cycles and partial transaction state on reset assertion [f_rst_1]

## Stimulus pseudocode

```text
1. SAMPLE on each clock edge wb_adr_i and wb_sel_i and wb_dat_i and wb_dat_o and wb_we_i and wb_stb_i and wb_cyc_i and wb_ack_o [f_addr_1,f_sel_1,f_wdat_1,f_rdat_1,f_we_1,f_stb_1,f_cyc_1,f_ack_1]
2. IF reset asserted THEN discard partial transaction and clear latency count and CONTINUE after deassertion [f_rst_1]
3. CAPTURE per-cycle request image with address and write-data and WE selection and STB and CYC framing and SEL select using SYM polarity without inventing active level [f_addr_1,f_wdat_1,f_we_1,f_stb_1,f_cyc_1,f_sel_1]
4. TRACK elapsed cycles from framed request to observed acknowledge and CAPTURE read-data at acknowledge to form ACK latency [f_ack_1,f_rdat_1]
5. EMIT one completed read or write register transaction per acknowledged transfer with address and data and control and latency to analysis ports and IGNORE unacknowledged idle cycles [f_addr_1,f_wdat_1,f_rdat_1,f_we_1,f_stb_1,f_cyc_1,f_ack_1]
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. FORWARD each completed register transaction via monitor analysis ports to register predictor and scoreboard subscribers for end-to-end comparison
2. SAMPLE each completed transaction in dedicated coverage subscriber tapping monitor analysis port for address direction and acknowledge observation
```

## Completion

1. WAIT for in-flight acknowledged transfer to emit or flush on reset then observe SYM_DRAIN_CYCLES idle cycles for pipeline drain
2. ENFORCE testbench operational timeout SYM_TIMEOUT_CYCLES as run limit not DUT timing requirement
3. CLEANUP clear partial transaction and latency state and release observation handles with no driven bus changes

## Questions

1. What are active levels and idle values of wb_we_i, wb_stb_i, wb_cyc_i and wb_ack_o for framing versus idle detection?
2. What defines transaction boundaries and acknowledge behavior for reconstruction: required STB and CYC combination, ACK duration, latency range, and back-to-back or pipelined handling?
3. What is active level and assert and deassert sequencing of wb_rst_i relative to the sampling clock edge and required flush behavior?
4. On which clock edge must the monitor sample and what symbolic period coordination applies without stating DUT timing?
5. What is bus address representation on wb_adr_i in DATA_BUS_WIDTH_8 build: 3-bit index versus 5-bit mode, handling of address 7, and meaning of wb_sel_i lanes for 8-bit data?
6. When is wb_dat_i versus wb_dat_o valid relative to framing and acknowledge, and how is wb_sel_i applied?

## Essential blockers


## Specification evidence

- `f_clk_1` → `/interfaces/groups/0` / `CH-63ad4d61a5`
> CLK 1 Input Block’s clock input

- `f_rst_1` → `/interfaces/groups/0` / `CH-63ad4d61a5`
> WB_RST_I 1 Input Asynchronous Reset

- `f_addr_1` → `/interfaces/groups/0` / `CH-63ad4d61a5`
> WB_ADDR_I 5 or 3 Input Used for register selection

- `f_sel_1` → `/interfaces/groups/0` / `CH-63ad4d61a5`
> WB_SEL_I 4 Input Select signal

- `f_wdat_1` → `/interfaces/groups/0` / `CH-63ad4d61a5`
> WB_DAT_I 32 or 8 Input Data input

- `f_rdat_1` → `/interfaces/groups/0` / `CH-63ad4d61a5`
> WB_DAT_O 32 or 8 Output Data output

- `f_we_1` → `/interfaces/groups/0` / `CH-63ad4d61a5`
> WB_WE_I 1 Input Write or read cycle selection

- `f_stb_1` → `/interfaces/groups/0` / `CH-63ad4d61a5`
> WB_STB_I 1 Input Specifies transfer cycle

- `f_cyc_1` → `/interfaces/groups/0` / `CH-63ad4d61a5`
> WB_CYC_I 1 Input A bus cycle is in progress

- `f_ack_1` → `/interfaces/groups/0` / `CH-63ad4d61a5`
> WB_ACK_O 1 Output Acknowledge of a transfer

- `f_bus_1` → `/sections/10/entries/3` / `CH-d62a4ba2db`
> The core implements the WISNBONE SoC bus interface for communication with the
> system.
