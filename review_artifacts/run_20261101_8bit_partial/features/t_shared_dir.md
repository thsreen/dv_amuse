# Shared address direction coverage

Work package: `t_shared_dir` · coverage · NEEDS_REVIEW

## Dependent features

- `t_uart_cfg`: Shared-address direction mapping coverage requires DLAB-gated normal versus divisor handling.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_loopback_stage`, `t_lsr_dr_cov`, `t_lsr_par_fram`, `t_modem_seq`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_serial_seq`, `t_traffic_err`, `t_wb_acc_cov`, `t_wb_mon`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

t_shared_dir is review-gated INFERRED register coverage of shared-address direction mapping receive versus transmit at address 0 and identification versus control at address 2, sampled on wishbone_bus monitor WE and wb_adr_i per-instance false, dependent on t_uart_cfg DLAB0 normal routing, bounded to DATA_BUS_WIDTH_8 responder build using RTL wb_adr_i wb_we_i names and spec register text; QUICK_TEST_PLAN_APPROVAL bins remain INFERRED navigation only, with only THR write direction DOCUMENTED so partial sampling is retained and complementary RB IIR FCR IER mappings await documentation.

## Preconditions

1. Clock stable and reset completed via common UVCs with DUT idle
2. t_uart_cfg dependency provides symbolic DLAB0 normal routing for addresses 0-1 access before shared-address sampling [f_dlab_1]
3. wishbone_bus active as WISHBONE responder interface with monitor observing wb_adr_i and WE direction and wb_ack_o completion [f_wb_1]
4. DATA_BUS_WIDTH_8 build with 8-bit register access [f_wb_1,f_thr_1]
5. serial_data external-device path idle with stx_pad_o observed and srx_pad_i untouched unlessQUESTION-tied [f_serial_1,f_pad_1]

## Stimulus pseudocode

```text
1. FOR DOCUMENTED direction IN [THR write at wb_adr_i pin value 0] DO spawn wishbone_bus write with symbolic WE-write indication and 8-bit payload under DLAB0 symbolic THEN WAIT for wb_ack_o completion OR UNTIL TESTBENCH request_timeout_cycles as operational limit [f_thr_1,f_dlab_1,f_wb_1]
2. IF RB read at 0 versus THR write and IIR read versus FCR write and IER RW become DOCUMENTED THEN FOR each confirmed direction DO spawn matching wishbone_bus read or write at same pin value ELSE SKIP pending questions without guessing
3. KEEP per-agent isolation: wishbone_bus sequence drives only wishbone_bus interface; serial_data and modem_control_if remain idle and untouched
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. SAMPLE regcov_shared_addr_dir via dedicated subscriber tapping wishbone_bus monitor analysis port on completed WISHBONE transfer using WE direction and wb_adr_i pin value, per-instance false
2. COVER addr0_write_THR on WE-write indication at wb_adr_i pin value 0 with DLAB0 normal routing symbolic [f_thr_1,f_dlab_1]
3. IF RB read at 0 and IIR read versus FCR write at 2 and IER RW at 1 become DOCUMENTED THEN SAMPLE addr0_read_RB and addr2_read_IIR and addr2_write_FCR and addr1_RW_IER ELSE leave uncovered pending questions, never invent mapping
4. HOLD illegal addr7 handling symbolic pending pin-value representation and legality confirmation, never compare an event with itself
5. RECORD per-instance false scope and review-gated status: QUICK_TEST_PLAN_APPROVAL coverage remains INFERRED navigation, not source authority
```

## Completion

1. WAIT all spawned wishbone_bus children complete OR UNTIL TESTBENCH request_timeout_cycles expires as operational limit only, not DUT timing
2. DRAIN wishbone_bus monitor for drain_cycles as TESTBENCH operational limit then close virtual sequence without VIFs or delays
3. CLEANUP return wishbone_bus driver to idle, release explicit sequencer handles, leave serial_data and modem_control_if untouched

## Questions

1. Confirm shared-address direction decoding for coverage: documented address access for Receiver Buffer read at 0 versus THR write at 0 and IIR read at 2 versus FIFO Control write at 2 and IER RW at 1? Only THR is documented; FIFO Control and Line Control items are empty and RB IIR IER lack documented items.
2. Confirm DLAB0 precondition for normal shared-address sampling: LCR DLAB bit position access reset value and MSB-first LSB-next divisor routing versus blocking of 0-1, and required programming order?
3. Confirm sampling event and encoding: ACK-qualified completed transfer versus address phase, WE value for read versus write, 3-bit wb_adr_i pin-value representation 0 to 6, and legality of addr7 for illegal_bins?
4. What are active owner or evidenced tie_off and inactive levels during this coverage for all DUT inputs: wb_rst_i polarity, wb_stb_i wb_cyc_i wb_we_i wb_sel_i levels, and drivers for srx_pad_i cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i while observing rts_pad_o dtr_pad_o int_o?
5. Confirm per-instance false scope, review-gate pass criteria for regcov_shared_addr_dir, and TESTBENCH request_timeout_cycles drain_cycles limits without implying DUT timing?

## Essential blockers


## Specification evidence

- `f_thr_1` → `/registers/registers/2` / `CH-f88915355b`
> Transmitter Holding
> Register (THR)
> 0 8 W Transmit FIFO input

- `f_dlab_1` → `/registers/registers/2` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set
> to ‘1’. At this time the above registers at addresses 0-1 can’t be accessed.

- `f_wb_1` → `/sections/10/entries/3` / `CH-d62a4ba2db`
> The core implements the WISNBONE SoC bus interface for communication with the
> system. It has an 8-bit data bus for compatibility reason.

- `f_pad_1` → `/sections/10/entries/4` / `CH-98be4510fb`
> STX_PAD_O 1 Output The serial output signal
> SRX_PAD_I 1 Input The serial input signal

- `f_serial_1` → `/interfaces/groups/5/property_evidence/function` / `CH-2baa4497c0`
> The UART (Universal Asynchronous Receiver/Transmitter) core provides serial
> communication capabilities
