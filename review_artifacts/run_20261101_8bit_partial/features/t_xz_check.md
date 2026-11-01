# XZ protocol check

Work package: `t_xz_check` · check · NEEDS_REVIEW

## Dependent features

- `t_wb_mon`: XZ protocol flagging on Wishbone signals requires bus monitor sampling established.
- `t_serial_mon`: XZ protocol flagging on serial pads requires serial monitor sampling established.
- `t_obs_mon`: XZ protocol flagging on modem signals requires passive modem observer sampling established.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_seq`, `t_shared_dir`, `t_traffic_err`, `t_uart_cfg`, `t_wb_acc_cov`, `t_wb_seq`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Implement passive XZ protocol checks flagging X or Z on WISHBONE responder ports RS232 serial pads and modem handshake signals on default clock sampling with immediate error, depending on established bus serial and modem monitor sampling.

## Preconditions

1. wishbone_bus passive monitor sampling established for DATA_BUS_WIDTH_8 responder
2. serial_data passive monitor sampling established for stx_pad_o tx and srx_pad_i rx
3. modem_control passive observer sampling established for rts_pad_o dtr_pad_o cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i
4. common clock stable and reset at symbolic inactive level with monitors driving nothing

## Stimulus pseudocode

```text
```

## Check pseudocode

```text
1. SAMPLE wishbone_bus ports wb_adr_i wb_sel_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o in monitor on SYM_CLK_DEFAULT_EDGE while reset inactive
2. IF any sampled wishbone_bus bit is X or Z THEN FLAG immediate protocol error for wishbone_bus XZ
3. SAMPLE serial_data ports stx_pad_o srx_pad_i in monitor on SYM_CLK_DEFAULT_EDGE while reset inactive
4. IF any sampled serial_data bit is X or Z THEN FLAG immediate protocol error for serial_data XZ
5. SAMPLE modem_control ports rts_pad_o dtr_pad_o cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i in observer on SYM_CLK_DEFAULT_EDGE while reset inactive
6. IF any sampled modem_control bit is X or Z THEN FLAG immediate protocol error for modem_control XZ
7. GATE all XZ flagging while reset asserted per symbolic SYM_RESET_GATING without assuming polarity or idle levels
```

## Coverage pseudocode

```text
```

## Completion

1. WAIT for monitor XZ evaluations to settle and event queues to drain within TEST_TIMEOUT_CYCLES operational limit not DUT timing
2. CLEANUP release monitor observation handles with monitors driving nothing

## Questions

1. Confirm which control and data signals are covered by XZ checks?
2. On which clock edge must wishbone_bus serial_data and modem_control XZ sampling occur given default CLK sampling only?
3. How must XZ checks be gated during wb_rst_i assertion and immediately after deassertion without inferring polarity?
4. Does XZ coverage include wb_sel_i wb_adr_i lanes and all modem inputs versus only outputs and data, and does it exclude int_o wb_clk_i and wb_rst_i itself?

## Essential blockers


## Specification evidence

- `f_wb_protocol` → `/interfaces/groups/0/property_evidence/protocol` / `CH-63ad4d61a5`
> 2.1 WISHBONE interface signals

- `f_wb_signals` → `/interfaces/groups/0` / `CH-63ad4d61a5`
> 2.1 WISHBONE interface signals

- `f_serial_rs232` → `/sections/1/entries/3` / `CH-2baa4497c0`
> like another computer using a serial cable and RS232 protocol.

- `f_modem_mcr` → `/sections/1/entries/4` / `CH-6abe65aeff`
> The modem control register allows transferring control signals to a modem connected to

- `f_data8` → `/sections/10/entries/3` / `CH-d62a4ba2db`
> It has an 8-bit data bus for compatibility reason.

- `f_xz_scope` → `/sections/8/entries/0` / `CH-32b051cdb1`
> UART IP Core
