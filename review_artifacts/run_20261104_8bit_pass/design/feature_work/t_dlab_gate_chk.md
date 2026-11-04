# DLAB gating check

Work package: `t_dlab_gate_chk` · verification_plan · NEEDS_REVIEW

## Dependent features

- `t_wb_mon`: DLAB gating check needs reconstructed completed WISHBONE transactions
- `t_wb_init_cfg`: DLAB set-clear stimulus must be programmed before gating check

## Independent features

`t_clk_cov`, `t_divisor_cov`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Verify DLAB gating on wishbone_slave_interface with RTL ports wb_adr_i wb_dat_i wb_dat_o wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i using pin values 0 1 3: divisor LSB and MSB at 0 and 1 accessible only when LCR bit7 is 1 and normal at 0 and 1 only when 0 with alias-toggle reads and RW compares at addr1 plus cross coverage; depends on monitor reconstruction and init divisor then clear programming; QUICK_TEST_PLAN_APPROVAL intentions stay INFERRED and spec-to-RTL map is reused with only DOCUMENTED facts constraining behavior.

## Preconditions

1. PRE_RESET_CLOCK: After reset driven via reset with clock running at fixed period per test; monitor flushes in-flight on reset and emits only completed ACK transactions; reset polarity and duration per questions with no invented level [f_post_reset f_div_reset_zero]
2. PRE_BIND: Canonical wishbone roles map to RTL ports wb_adr_i_2_0 wb_dat_i_7_0 wb_dat_o_7_0 wb_we_i wb_stb_i wb_cyc_i wb_ack_o wb_sel_i with UART_DATA_WIDTH 8 UART_ADDR_WIDTH 3 DATA_BUS_WIDTH_8; write and read addresses are bus pin values 0 1 3 not offsets [f_lcr_addr f_rbr_addr f_dll_addr f_dlm_addr]
3. PRE_OWNERSHIP: wishbone_slave_interface agent drives wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i and observes wb_dat_o wb_ack_o; interrupt_output observes int_o; uart_serial_data holds srx_pad_i and stx_pad_o idle; modem_control_if holds cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i rts_pad_o dtr_pad_o idle; no handshake or flow-control inactive levels invented
4. PRE_BASELINE: Post-reset LCR 00000011b divisor 0 IER 00h with FIFOs cleared; init programming completed MSB-first LSB-next with DLAB 1 then cleared to 0 leaving DLAB 0 and bus idle-owned for gating handoff [f_lcr_reset f_div_reset_zero f_ier_reset f_div_order f_restore]
5. PRE_MONITOR: Wishbone monitor samples on clock edges and reconstructs completed reads and writes on ACK assertion for analysis port to checker scoreboard and coverage

## Stimulus pseudocode

```text
1. STIM_WAIT_START: WAIT reset deassert via reset; WAIT bus idle-owned; START wishbone monitor to reconstruct ACK completions
2. STIM_BASIC_DLAB1: WRITE LCR pin 3 data SYM_LCR_DLAB1 with bit7 1 from documented baseline via wishbone_slave_interface; WAIT ACK [f_lcr_addr f_dlab_one f_dlab_set]
3. STIM_BASIC_DIV_PROG: WRITE pin 1 data SYM_DIV_MSB then WRITE pin 0 data SYM_DIV_LSB MSB-first LSB-next via same agent; WAIT ACK each [f_dll_addr f_dlm_addr f_div_order f_div_two_bytes]
4. STIM_BASIC_DIV_READ: READ pin 1 and pin 0 with DLAB 1 via same agent; HOLD data for CHECK_DIV_DLAB1; WAIT ACK
5. STIM_BASIC_DLAB0: WRITE LCR pin 3 data SYM_LCR_DLAB0 with bit7 0 via same agent; WAIT ACK [f_dlab_zero f_restore]
6. STIM_BASIC_IER: WRITE pin 1 data SYM_IER_PATTERN with bits 3-0 documented enables and bits 7-4 zero via same agent; WAIT ACK; READ pin 1 with DLAB 0 via same agent; HOLD for CHECK_IER_DLAB0 [f_ier_enable f_ier_reserved]
7. STIM_TOGGLE: WRITE LCR DLAB 1; READ pin 1 for divisor alias; WRITE LCR DLAB 0; READ pin 1 for normal alias; FOR documented IER enable sweep repeat IER write and read with DLAB 0; WAIT ACK each
8. STIM_CLEANUP: LEAVE LCR DLAB 0; WAIT bus idle-owned; FLUSH in-flight; END stimulus
```

## Check pseudocode

```text
1. CHECK_DIV_DLAB1: COMPARE divisor reads at pin 0 and 1 with written SYM_DIV_LSB and SYM_DIV_MSB mask 0xFF when DLAB equals 1; FAIL on data mismatch [f_dlab_one f_dll_addr f_dlm_addr f_div_order]
2. CHECK_IER_DLAB0: COMPARE IER read at pin 1 with SYM_IER_PATTERN mask 0x0F for bits 3-0 plus reserved check 0xF0 equals 0 when DLAB equals 0; FAIL on mismatch [f_dlab_zero f_ier_enable f_ier_reserved]
3. CHECK_ALIAS_TOGGLE: COMPARE toggle proof that pin 1 read with DLAB 1 equals divisor and not normal and pin 1 read with DLAB 0 equals normal and not divisor; FAIL on unexpected acceptance or alias leakage [f_alias_block f_dlab_set f_restore]
4. CHECK_PROTOCOL_CLASS: ASSERT on each completed ACK transaction at pin 0 and 1 that alias class matches DLAB context, pin 0 DLAB1 is DLL and DLAB0 is RBR_THR, pin 1 DLAB1 is DLM and DLAB0 is IER; FAIL on class mismatch [f_alias_block f_rbr_addr f_dll_addr f_dlm_addr]
5. CHECK_PLUMBING: CHECK sampled wishbone pins never X or Z in ACK window and known after reset as infrastructure, not DUT oracle
```

## Coverage pseudocode

```text
1. COV_CROSS_DLAB: SAMPLE cg_cross_addr_dlab cross_addr_X_dlab bins addr0_dlab0_RBR_THR addr0_dlab1_DLL addr1_dlab0_IER addr1_dlab1_DLM addr2_to_6 normal illegal addr_7 on each WB_ACK_O completion via dedicated subscriber tapping wishbone monitor analysis port; drivers never supply coverage [f_cross_alias f_rbr_addr f_dll_addr f_dlm_addr]
2. COV_DIV_BYTES: SAMPLE rc_divisor_bytes cp_divisor_value for LSB and MSB values on divisor-byte write completion with DLAB 1, ignore DLAB 0, via same subscriber [f_div_two_bytes f_div_msb_desc]
3. COV_ASSERT: PROVIDE property and activation covers for DLAB gating assertion
```

## Completion

1. DONE when LCR DLAB1 plus MSB-first plus LSB-next plus divisor reads plus LCR DLAB0 plus IER write plus IER read plus alias toggle reads all ACKed and COMPAREs pass and cross plus divisor coverage SAMPLED
2. BOUND by TEST_TIMEOUT_CYCLES plus drain_cycles and request_timeout_cycles as TESTBENCH operational limits not DUT timing; TIMEOUT is testbench failure
3. CLEANUP leaves LCR DLAB 0 with wishbone bus idle-owned for traffic handoff; TERMINATE on traffic done or operational timeout

## Questions

1. What is documented normal versus divisor alias map at pin addresses 0-1 under DLAB 0 versus 1, confirming normal addr0 RBR_R versus THR_W and addr1 IER_RW versus divisor LSB_RW at 0 MSB_RW at 1, and is mismatched access an alias return versus blocked or ignored with what ACK and read data?
2. What is active level polarity of wb_rst_i, required reset duration in clock cycles, and must monitor flush in-flight versus flag reset-during-transfer as error, and what is clock sampling edge for ACK reconstruction given fixed period per test?
3. What are documented WISHBONE handshake semantics for reconstruction: stability of wb_adr_i wb_we_i wb_sel_i wb_stb_i wb_cyc_i during transfer, wb_ack_o single versus multi-cycle window, wb_dat_o validity on reads, and back-to-back handling?
4. What is documented wb_sel_i legal values in DATA_BUS_WIDTH_8 build, address representation as pin values 0-6 versus offsets, and handling of illegal pin address 7?
5. What symbolic divisor LSB and MSB values form legal nonzero divisor for bring-up, is divisor zero illegal beyond reset disabling serial I/O, and is MSB-first LSB-last order mandatory given counter starts on LSB write?
6. What LCR bits 6-0 line parameters must accompany DLAB 1 then 0 during gating check, and what comparison masks apply to IER reserved bits 7-4 versus enables 3-0?
7. What is expected read data for address 0 FIFO alias during gating given side-effect behavior, and should address 0 be coverage-only without data COMPARE with simple RW mirror limited to address 1 IER versus DLM?

## Essential blockers


## Specification evidence

- `f_dlab_one` → `/registers/registers/7/fields/6` / `CH-bc7559f2ec`
> ‘1’ – The divisor latches can be accessed

- `f_dlab_zero` → `/registers/registers/7/fields/6` / `CH-bc7559f2ec`
> ‘0’ – The normal registers are accessed

- `f_lcr_addr` → `/registers/registers/7` / `CH-f88915355b`
> Line Control Register 3 8 RW Control connection

- `f_lcr_reset` → `/registers/registers/7` / `CH-bc7559f2ec`
> Reset Value: 00000011b

- `f_div_two_bytes` → `/registers/registers/13` / `CH-06bad6ffcd`
> The 2 bytes form one 16-bit register, which is

- `f_div_reset_zero` → `/registers/registers/13` / `CH-06bad6ffcd`
> The register is set to the default value of 0 on reset, which

- `f_div_order` → `/sections/1/entries/9` / `CH-06bad6ffcd`
> write the MSB first and the LSB last.

- `f_alias_block` → `/registers/registers/1` / `CH-f88915355b`
> At this time the above registers at addresses 0-1 can’t be accessed.

- `f_dlab_set` → `/sections/1/entries/9` / `CH-06bad6ffcd`
> The divisor latches can be accessed by setting the 7th bit of LCR to ‘1’.

- `f_restore` → `/sections/1/entries/9` / `CH-06bad6ffcd`
> restore this bit to ‘0’ after setting the divisor latches in order to restore access to the other

- `f_rbr_addr` → `/registers/registers/1` / `CH-f88915355b`
> Receiver Buffer 0 8 R Receiver FIFO output

- `f_dll_addr` → `/sections/9/entries/5` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor

- `f_dlm_addr` → `/sections/9/entries/5` / `CH-f88915355b`
> Divisor Latch Byte 2 1 8 RW The MSB of the divisor

- `f_ier_enable` → `/sections/8/entries/2` / `CH-de51b2eafc`
> This register allows enabling and disabling interrupt generation by the UART.

- `f_ier_reserved` → `/sections/8/entries/2` / `CH-de51b2eafc`
> 7-4 RW Reserved. Should be logic ‘0’.

- `f_ier_reset` → `/sections/8/entries/2` / `CH-de51b2eafc`
> Reset Value: 00h

- `f_post_reset` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> All interrupts are disabled in the Interrupt Enable Register.

- `f_cross_alias` → `/sections/9/entries/5` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set

- `f_div_msb_desc` → `/sections/9/entries/9` / `CH-f88915355b`
> The MSB of the divisor
