# WISHBONE agent scoreboard

Work package: `t_wb_scoreboard` · checks · NEEDS_REVIEW

## Dependent features

- `t_wb_mon`: request-answer matching needs completed transactions

## Independent features

`t_addr_dlab_cov`, `t_chip_reset`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_init_cfg`, `t_wb_reg_cov`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

WISHBONE agent scoreboard inside wishbone_slave_interface agent tracks monitor-reported completed transactions to detect lost duplicated or misordered transfers with read-data comparison only where documented reference exists; eventually-answered uses testbench timeout not documented DUT bound provenance INFERRED quick-test only.

## Preconditions

1. wishbone_slave_interface monitor reconstructs completed transactions on wb_ack_o observed on clock edges and emits to analysis port with in-flight flushed on wb_rst_i
2. clock period fixed per test with reset via common clock and reset not agents
3. wishbone_slave_interface driver owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i during traffic; serial and modem inputs owned by their agents and not driven here
4. Write and read addresses are pin values wb_adr_i with reset polarity unresolved per questions; request_timeout_cycles and drain_cycles are TESTBENCH operational limits
5. Scoreboard subscribed to monitor analysis port with separate pending request queue; acknowledge latency bound is testbench limit provenance INFERRED for quick testing only

## Stimulus pseudocode

```text
```

## Check pseudocode

```text
1. SAMPLE completed read and write transactions from wishbone_slave_interface monitor analysis port where completion is monitor-reported wb_ack_o assertion on clock edges
2. FOR each sampled completion APPEND to observed queue retaining wb_adr_i wb_we_i wb_sel_i wb_dat_i wb_dat_o ordering
3. COMPARE observed queue against pending request queue in order: IF head request matches address plus we plus sel plus dat_i RETIRE as answered; IF identifier already retired FLAG duplicated; IF payload order differs FLAG misordered
4. IF sampled completion is read AND documented reference expected data is available COMPARE wb_dat_o under explicit mask; ELSE RECORD wb_dat_o without PASS versus FAIL on value
5. WAIT for traffic done THEN WAIT drain_cycles THEN WAIT request_timeout_cycles as TESTBENCH operational limits; FOR any pending request with no observed completion FLAG potentially lost against testbench timeout not DUT bound
6. ON wb_rst_i FLUSH pending plus in-flight per monitor flush rule and RESET scoreboard counters; CLEANUP queues and counters at test end
```

## Coverage pseudocode

```text
```

## Completion

1. Scoreboard active from reset release through traffic until drain_cycles plus request_timeout_cycles elapse or TEST_TIMEOUT_CYCLES operational limit
2. At least one observed versus pending queue comparison attempted when traffic present
3. drain_cycles and request_timeout_cycles are TESTBENCH operational limits not DUT acknowledge requirements

## Questions

1. What is documented acknowledge behavior defining eventually-answered bound as testbench limit?
2. What defines correct wb_dat_o on reads for pin addresses 0-6 including DLAB gating reset values and clear-on-read side effects for scoreboard reference?
3. What defines WISHBONE request identity for loss or duplication including required wb_stb_i wb_cyc_i wb_we_i wb_sel_i wb_adr_i stability ACK assertion window single versus multi-cycle back-to-back handling and legal wb_sel_i in DATA_BUS_WIDTH_8?
4. What are active level polarity of wb_rst_i and required duration in clock cycles and required scoreboard versus monitor behavior on reset-during-transfer flush versus error?

## Essential blockers


## Specification evidence

- `f_wb_slave_if_1` → `/sections/1/entries/2` / `CH-2baa4497c0`
> WISHBONE interface in 32-bit or 8-bit data bus modes (selectable)
