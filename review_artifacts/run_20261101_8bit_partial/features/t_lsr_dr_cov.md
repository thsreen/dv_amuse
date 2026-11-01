# LSR data-ready and coverage

Work package: `t_lsr_dr_cov` · check · NEEDS_REVIEW

## Dependent features

- `t_loopback_stage`: LSR data-ready overrun parity framing break coverage requires staged FIFO traffic with errors.

## Independent features

`t_clk_cov`, `t_cross_int_traffic`, `t_div_dlab_cov`, `t_ier_iir_en`, `t_ier_reset`, `t_iir_cov`, `t_iir_prio_fixed`, `t_lsr_par_fram`, `t_obs_mon`, `t_overrun_burst`, `t_reset_div_known`, `t_reset_fifo_lcr`, `t_serial_mon`, `t_shared_dir`, `t_traffic_err`, `t_wb_acc_cov`, `t_wb_mon`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Verify LSR DR tracks Receiver FIFO occupancy and cover DR overrun parity framing break and error-summary via staged loopback plus error traffic, sampling LSR reads and comparing against serial and bus observations.

## Preconditions

1. Clock running at fixed test period with reset asserted then released; DUT in DATA_BUS_WIDTH_8 build
2. wishbone_bus owns wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i and observes wb_dat_o wb_ack_o; serial_data owns srx_pad_i and observes stx_pad_o; modem_control_if owns cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i; uart_interrupt observes int_o
3. LSR reachable by WISHBONE read at address 5 as read-only status [f_lsr_1]
4. Staged FIFO traffic from t_loopback_stage available symbolically for fill drain and error bursts; serial format divisor bit_cycles and FIFO depth remain symbolic

## Stimulus pseudocode

```text
1. IF bring-up THEN drive one clean serial frame via serial_data at symbolic format divisor THEN WISHBONE read LSR via wishbone_bus at address 5 [f_lsr_1] [f_dr_1]
2. FOR occupancy THEN burst serial frames to fill FIFO THEN pop via symbolic Receiver Buffer reads with varied timing THEN reread LSR after each pop [f_dr_1]
3. FOR parity framing break THEN inject bad-parity frame THEN missing-stop frame THEN held-zero break for one symbolic character time via serial_data THEN read LSR after each [f_pe_1] [f_fe_1] [f_bi_1]
4. FOR overrun THEN burst to FIFO full THEN inject extra character while full with varied pop timing THEN read LSR [f_oe_1]
5. AFTER each error burst drive clean frames to recover then reread LSR to confirm DR follows occupancy
```

## Check pseudocode

```text
1. COMPARE LSR bit0 DR against Receiver FIFO occupancy on each LSR read: EXPECT 1 when at least one character in FIFO ELSE 0 [f_dr_1]
2. COMPARE LSR OE when FIFO full and extra character in shift register with FIFO intact; PE when top character has parity error; FE when top character lacks valid stop bit; BI when break hold produced zero character [f_oe_1] [f_pe_1] [f_fe_1] [f_bi_1]
3. COMPARE clear-on-read: reread LSR after first read; EXPECT OE PE FE BI cleared while DR continues to follow occupancy and pop sequence exposes next character status [f_oe_1] [f_pe_1] [f_fe_1] [f_bi_1] [f_dr_1]
4. COMPARE Receiver Line Status interrupt pending when OE PE FE BI set with reset by reading LSR [f_rls_1] [f_oe_1] [f_pe_1]
```

## Coverage pseudocode

```text
1. SAMPLE LSR value on each WISHBONE LSR read at clock edge via wishbone_bus monitor with serial_data scoreboard comparison
2. COVER lsr_dr bins empty versus data_ready derived from occupancy comparison [f_dr_1]
3. COVER lsr_error_class bins no_error parity framing overrun break multiple summary_set as inferred sampling; clear-on-read verified by paired scoreboard not coverage alone [f_oe_1] [f_pe_1] [f_fe_1] [f_bi_1]
```

## Completion

1. WAIT all LSR read and FIFO drain operations complete OR UNTIL TESTBENCH request_timeout_cycles expires as operational limit only
2. DRAIN wishbone_bus plus serial_data plus modem_control_if monitors for drain_cycles as TESTBENCH operational limit then close sequence
3. CLEANUP deassert wishbone_bus strobes to symbolic idle, release sequencer handles, leave serial_data and modem_control_if at symbolic idle

## Questions

1. Confirm error-summary bit number semantics and clear-on-read behavior for coverage: CH-4e1d3a956c indicates at least one parity framing break inside FIFO but no DOCUMENTED field is supplied?
2. Confirm Receiver Buffer read address access and FIFO depth plus trigger level for DR empty versus non-empty transitions and overrun fill with varied pop timing?
3. Confirm WISHBONE read signaling for LSR at address 5 including wb_sel_i wb_we_i wb_stb_i wb_cyc_i wb_ack_o handshake and address representation, plus wb_rst_i polarity and inactive levels?
4. Confirm serial configuration and divisor-derived bit_cycles including LCR format parity stop programming order and break hold of one character time for parity framing break injection and clean recovery?
5. Confirm read-clear scope: DR follows occupancy versus OE PE FE BI cleared on LSR read, and effect of Receiver Buffer pop exposing next character error bits, plus LSR reset value?
6. Confirm owners tie_offs and idle levels for all DUT inputs during LSR tests and TESTBENCH drain_cycles request_timeout_cycles operational limits?

## Essential blockers


## Specification evidence

- `f_dr_1` → `/sections/8/entries/8` / `CH-a2dd758e55`
>  ‘0’ – No characters in the FIFO
>  ‘1’ – At least one character has been received and is in the
> FIFO.

- `f_oe_1` → `/sections/8/entries/9` / `CH-a2dd758e55`
>  ‘1’ – If the FIFO is full and another character has been
> received in the receiver shift register. If another character is starting
> to arrive, it will overwrite the data in the shift register but the FIFO
> will remain intact. The bit is cleared upon reading from the register.
> Generates Receiver Line Status interrupt.

- `f_pe_1` → `/sections/8/entries/10` / `CH-a2dd758e55`
>  ‘1’ – The character that is currently at the top of the FIFO
> has been received with parity error. The bit is cleared upon reading
> from the register. Generates Receiver Line Status interrupt.

- `f_fe_1` → `/sections/8/entries/11` / `CH-a2dd758e55`
>  ‘1’ – The received character at the top of the FIFO did not
> have a valid stop bit. Of course, generally, it might be that all the
> following data is corrupt. The bit is cleared upon reading from the
> register. Generates Receiver Line Status interrupt.

- `f_bi_1` → `/registers/registers/9/fields/4` / `CH-a2dd758e55`
> The break occurs when the line is held in logic 0 for a
> time of one character (start bit + data + parity + stop bit). In that
> case, one zero character enters the FIFO and the UART waits for a
> valid start bit to receive next character. The bit is cleared upon
> reading from the register. Generates Receiver Line Status interrupt.

- `f_lsr_1` → `/registers/registers/9` / `CH-f88915355b`
> Line Status 5 8 R Status information

- `f_rls_1` → `/sections/8/entries/6` / `CH-f91cbf1c05`
> 0 1 1 1 st Receiver Line
> Status
> Parity, Overrun or Framing
> errors or Break Interrupt
> Reading the Line
> Status Register
