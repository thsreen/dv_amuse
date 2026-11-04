# Address by DLAB cross

Work package: `t_addr_dlab_cov` · coverage · NEEDS_REVIEW

## Dependent features

- `t_dlab_gate_chk`: address by DLAB cross builds on divisor versus normal aliasing check

## Independent features

`t_clk_cov`, `t_divisor_cov`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Cover WISHBONE pin address crossed with LCR DLAB gating for divisor versus normal aliasing at 0-1 plus normal 2-6 and illegal 7 sampled on ACK completion via wishbone_slave_interface monitor.

## Preconditions

1. DUT is responder on wishbone_slave_interface using physical ports wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i with UART_ADDR_WIDTH 3 UART_DATA_WIDTH 8 DATA_BUS_WIDTH_8; pin addresses 0 1 are aliased by DLAB
2. Clock period fixed per test with reset applied via reset itself before traffic; wishbone_slave_interface agent owns its driven inputs and observes outputs; other interfaces idle-observed only
3. LCR at pin address 3 provides symbolic DLAB1_DIVISOR selecting divisor latches at 0-1 and DLAB0_NORMAL selecting normal registers at 0-1
4. Monitor reconstructs completed transactions on WB_ACK_O observed on clock edge; dedicated coverage subscriber taps monitor analysis port
5. Dependency t_dlab_gate_chk alias handling is architectural prerequisite; this feature adds only address by DLAB cross sampling

## Stimulus pseudocode

```text
1. Bring-up via wishbone_slave_interface agent only: WAIT for reset done and bus idle then program LCR at pin address 3 to symbolic DLAB1_DIVISOR
2. FOR DLAB in [DLAB1_DIVISOR then DLAB0_NORMAL]: IF DLAB1 drive divisor alias accesses at pin addr 0 LSB RW and pin addr 1 MSB RW; IF DLAB0 drive normal accesses at pin addr 0 RBR read plus THR write and pin addr 1 IER RW using symbolic legal byte data
3. FOR each DLAB state drive pin addresses 2 3 4 5 6 with read and write where documented access permits to hit addr2_to_6 bins
4. Drive pin address 7 read and write attempt under each DLAB to observe illegal addr_7_any_dlab disposition without assuming ACK or data behavior
5. WAIT for WB_ACK_O completion per transfer within request_timeout_cycles operational limit; FOR random exploration vary order of addr-DLAB combinations with directed DLAB programming retained; TERMINATE on all bins driven or operational timeout
6. CLEANUP program LCR to DLAB0_NORMAL and leave wishbone bus idle-owned for handoff
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. SAMPLE cg_cross_addr_dlab.cross_addr_X_dlab on each WB_ACK_O completion observed on clock edge via dedicated subscriber tapping wishbone_slave_interface monitor; drivers never supply coverage events
2. COMPARE observed pin value wb_adr_i in 0 1 2 3 4 5 6 plus 7 against current DLAB state from LCR bit7 to bins addr0_dlab0_RBR_THR addr0_dlab1_DLL_SB addr1_dlab0_IER addr1_dlab1_DLM_SB addr2_to_6_dlab0_normal addr2_to_6_dlab1 plus illegal addr_7_any_dlab
3. SAMPLE per-instance false single UART instance Tier 2 configuration cross; exclude configuration-write payload semantics from cross; no data COMPARE in coverage
4. WAIT for ACK completion for each driven address-DLAB combination; TERMINATE sampling on all supported bins hit or operational timeout
```

## Completion

1. DONE when cg_cross_addr_dlab cross_addr_X_dlab bins addr0_dlab0_RBR_THR plus addr0_dlab1_DLL_SB plus addr1_dlab0_IER plus addr1_dlab1_DLM_SB plus addr2_to_6_dlab0_normal plus addr2_to_6_dlab1 SAMPLED and illegal addr_7_any_dlab disposition recorded
2. BOUND by TEST_TIMEOUT_CYCLES plus drain_cycles and request_timeout_cycles as TESTBENCH operational limits not DUT timing; TIMEOUT is testbench failure
3. CLEANUP leaves LCR DLAB 0 with wishbone bus idle-owned for traffic handoff; TERMINATE on coverage done or operational timeout

## Questions

1. What is active polarity of wb_rst_i required reset duration clock sampling edge for ACK reconstruction and must monitor flush in-flight versus flag reset-during-transfer as error?
2. What are documented WISHBONE handshake semantics: stability of wb_adr_i wb_we_i wb_sel_i wb_stb_i wb_cyc_i during transfer wb_ack_o single versus multi-cycle window wb_dat_o validity on reads and back-to-back handling?
3. What are wb_sel_i legal values in DATA_BUS_WIDTH_8 build is address representation pin values 0-6 versus offsets and what is handling of illegal pin address 7 and mismatched DLAB access at 0-1 with ACK and read data alias versus blocked?
4. What is expected read data for address 0 FIFO alias during gating given side-effect behavior should addr0 be coverage-only without data COMPARE and what masks apply to IER reserved bits and LCR bits 6-0 when programming DLAB?

## Essential blockers


## Specification evidence

- `f_alias_blocked` → `/sections/9/entries/5` / `CH-f88915355b`
> At this time the above registers at addresses 0-1 can’t be accessed.

- `f_div_access` → `/sections/9/entries/5` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set

- `f_lsb` → `/registers/registers/0` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor

- `f_msb` → `/registers/registers/3` / `CH-f88915355b`
> Divisor Latch Byte 2 1 8 RW The MSB of the divisor

- `f_rbr` → `/registers/registers/1` / `CH-f88915355b`
> Receiver Buffer 0 8 R Receiver FIFO output

- `f_thr` → `/registers/registers/2` / `CH-f88915355b`
> 0 8 W Transmit FIFO input

- `f_ier` → `/sections/9/entries/8` / `CH-f88915355b`
> Interrupt Enable 1 8 RW Enable/Mask interrupts

- `f_lcr_addr` → `/sections/9/entries/8` / `CH-f88915355b`
> Line Control Register 3 8 RW Control connection
