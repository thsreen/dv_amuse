# UART serial data monitor

Work package: `t_uart_mon` · verification_plan · NEEDS_REVIEW

## Dependent features

- `t_wb_init_cfg`: serial sampling relative to programmed divisor needs init divisor first

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_baud_mon`, `t_irq_id_cov`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Build uart_serial_data monitor observing stx_pad_o and driving srx_pad_i timing via programmed divisor to reconstruct TX RX bytes with framing break attributes, after wishbone divisor bring-up, using symbolic line format pending source confirmation

## Preconditions

1. Clock is active and reset has completed generically; reset polarity unresolved so use asserted versus deasserted only; monitor discards partial frames on reset and realigns to next start bit
2. Bindings: wb_clk_i driven by clock, wb_rst_i driven by reset, wb_adr_i 3-bit pin values plus wb_dat_i wb_we_i wb_stb_i wb_cyc_i wb_sel_i owned by wishbone_slave_interface, srx_pad_i driven by uart_serial_data, cts_pad_i dsr_pad_i ri_pad_i dcd_pad_i owned by modem_control_if, stx_pad_o plus wb_dat_o wb_ack_o int_o observed
3. Divisor programmed nonzero via DLAB sequence per f_divisor_access f_divisor_order f_divisor_lsb_addr f_divisor_msb_addr f_dlab_access with DLAB restored to 0; divisor 0 disables I/O per f_divisor_reset; BIT_CYCLES held symbolic from f_divisor_baud using clock
4. Line format data_bits parity stop_bits held symbolic pending source confirmation; configuration bus writes must agree with uart_serial_data monitor settings; bus addresses are pin values LSB equals 0 MSB equals 1

## Stimulus pseudocode

```text
1. FOR bring-up: wishbone_slave_interface drives LCR DLAB equals 1 write then MSB write to pin address 1 then LSB write to pin address 0 then LCR DLAB equals 0 write using symbolic nonzero divisor per f_divisor_order; WAIT for wb_ack_o; leave bus idle-owned
2. FOR RX exercise: uart_serial_data driver drives srx_pad_i frames using symbolic data_bits parity stop_bits timed by symbolic BIT_CYCLES derived from programmed divisor per f_divisor_baud; WAIT for monitor to emit RX byte transaction to analysis port
3. FOR TX observation: observe stx_pad_i versus stx_pad_o frames passively timed by same BIT_CYCLES; monitor emits TX byte transaction to analysis port without driving; IF reset asserted THEN discard partial frames and WAIT for next start bit
4. Virtual coordination spawns wishbone payload and uart frame traffic concurrently; stages execute in order with no VIFs or delays in virtual sequence; per-agent sequences drive only own interface
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. SAMPLE rc_divisor_bytes on divisor-byte write completion via subscriber tapping wishbone monitor analysis port filtered by address 0 versus 1 with DLAB equals 1
2. Cover lsb_zero_0x00 lsb_mid_0x01_0xFE lsb_max_0xFF msb_zero_0x00 msb_mid_0x01_0xFE msb_max_0xFF combined_zero_disables combined_nonzero_enables; drivers never supply coverage
```

## Completion

1. Done when divisor bring-up ACKed with DLAB equals 0 and uart_serial_data monitor has emitted TX plus RX byte transactions to analysis port or TEST_TIMEOUT_CYCLES expires
2. Bound by TEST_TIMEOUT_CYCLES and drain_cycles as testbench operational limits not DUT timing; on reset WAIT then discard partial frames and realign to next start bit
3. Cleanup leaves DLAB equals 0 with wishbone bus idle-owned by wishbone_slave_interface and srx_pad_i idle-owned by uart_serial_data

## Questions

1. What are source-stated data_bits options for LCR bits 1-0 including 5 6 7 8 and reset 00000011b meaning for monitor reconstruction?
2. What are source-stated parity enable even stick rules for LCR bits 3-5 including odd versus even number of 1s for transmit generation versus receive checking?
3. What are source-stated stop_bits options for LCR bit 2 including 1 versus 1_5 versus 2 and receiver first-stop-only checking?
4. What is exact divisor-to-bit timing for sampling: is BIT_CYCLES divisor times 16 clocks from Input Clock divided by Divisor equals 16 times baud including mid-bit sampling offset?
5. What are idle start stop break levels on srx_pad_i and stx_pad_o and break duration start plus data plus parity plus stop versus held 0 for framing versus break attributes?
6. What is wb_rst_i polarity and required deassert-to-first-write delay and FCR trigger plus IER plus LCR 6-0 values needed during bring-up to observe bytes without loss?
7. What is wb_adr_i 3-bit pin representation for divisor overlap with THR RBR at 0-1 under DLAB and wb_sel_i usage under DATA_BUS_WIDTH_8?

## Essential blockers


## Specification evidence

- `f_divisor_access` → `/registers/registers/13` / `CH-06bad6ffcd`
> The divisor latches can be accessed by setting the 7th bit of LCR to ‘1’.

- `f_divisor_width` → `/registers/registers/13` / `CH-06bad6ffcd`
> The 2 bytes form one 16-bit register, which is
> internally accessed as a single number.

- `f_divisor_reset` → `/registers/registers/13` / `CH-06bad6ffcd`
> The register is set to the default value of 0 on reset, which
> disables all serial I/O operations in order to ensure explicit setup of the register in the
> software.

- `f_divisor_baud` → `/registers/registers/13` / `CH-06bad6ffcd`
> The value set should be equal to (system clock speed) / (16 x desired baud rate).

- `f_divisor_order` → `/registers/registers/13` / `CH-06bad6ffcd`
> The internal counter starts to work when the LSB of DL is written, so when setting the
> divisor, write the MSB first and the LSB last.

- `f_serial_pins` → `/interfaces/groups/4/property_evidence/function` / `CH-98be4510fb`
> STX_PAD_O 1 Output The serial output signal
> SRX_PAD_I 1 Input The serial input signal

- `f_divisor_lsb_addr` → `/sections/9/entries/9` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor

- `f_divisor_msb_addr` → `/sections/9/entries/9` / `CH-f88915355b`
> Divisor Latch Byte 2 1 8 RW The MSB of the divisor

- `f_dlab_access` → `/sections/9/entries/9` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set
> to ‘1’.
