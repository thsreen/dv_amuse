# WISHBONE top stimulus

Work package: `t_wb_top_seq` · stimulus · NEEDS_REVIEW

## Dependent features

- `t_wb_init_cfg`: controlled register stimulus reuses init DLAB-gating base sequence

## Independent features

`t_addr_dlab_cov`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_irq_baud_mon`, `t_irq_err_chk`, `t_irq_id_cov`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_traffic_seq`, `t_uart_mon`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

WISHBONE top sequence on wishbone_slave_interface_agent drives controlled register reads and writes within documented addresses 0-6 with DLAB gating, reusing init DLAB base; clock fixed per test, coverage sampled on completion.

## Preconditions

1. Chip reset completed with FIFOs cleared and reset values applied [f_reset_div_zero] [f_reset_lcr_8n1] [f_reset_ier_disabled], clock period fixed per test before traffic
2. init_config_sequence completed with MSB-first divisor programming then DLAB cleared to 0 for normal-register handoff [f_div_order_msb_first] [f_dlab_disable_access] [f_dlab_enable_access]
3. wishbone_slave_interface_agent owns DUT inputs wb_adr_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i and observes wb_dat_o wb_ack_o on clock edges; bus idle before start

## Stimulus pseudocode

```text
1. WAIT for init handoff with tracked DLAB=0 and wishbone bus idle
2. FOR each directed bring-up slot in documented order: drive one access via wishbone_slave_interface_agent only using wb_adr_i for pin address value, wb_we_i for documented direction, wb_dat_i for symbolic write byte; WAIT for wb_ack_o completion on observed clock edges before next start [f_rbr_addr0] [f_thr_addr0] [f_ier_addr1] [f_iir_fcr_addr2] [f_lcr_addr3] [f_mcr_lsr_msr_addr456]
3. IF tracked DLAB==0 THEN constrain addr to 0 to 6 normal mapping with documented R/W/RW per address [f_rbr_addr0] [f_thr_addr0] [f_ier_addr1] [f_iir_fcr_addr2] [f_lcr_addr3] [f_mcr_lsr_msr_addr456]; ELSE IF tracked DLAB==1 THEN constrain addr to 0 divisor LSB and 1 divisor MSB RW only [f_dll_lsb] [f_dlm_msb] [f_dlab_gate_divisor] [f_dlab_gate_normal_blocked]
4. FOR N controlled transactions under reproducible seed with volume and idle knobs as testbench operational limits: randomize symbolic addr, symbolic data byte class, and read-vs-write within documented access types and current DLAB gating; update tracked DLAB on LCR bit7 writes respecting MSB-first then LSB-next divisor order [f_div_order_msb_first] [f_dlab_enable_access] [f_dlab_disable_access]; drive back-to-back or idle gaps without changing clock period
5. On LCR write changing DLAB: IF new DLAB==1 THEN next divisor accesses use addr 0 LSB and addr 1 MSB; IF new DLAB==0 THEN return to normal 0-6 mapping [f_dlab_gate_divisor] [f_dlab_gate_normal_blocked] [f_dll_lsb] [f_dlm_msb]
6. Cleanup: drive LCR write to clear DLAB to 0, WAIT for completion, leave wishbone bus idle-owned for traffic handoff [f_dlab_disable_access]
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. SAMPLE cg_wb_reg_access for addr 0-6 with read/write direction and byte data class on each completion via wishbone monitor analysis port [f_ier_addr1] [f_mcr_lsr_msr_addr456]
2. SAMPLE rc_wb_regs for reg0 RBR vs THR, reg1 IER, reg2 IIR vs FCR, reg3 LCR, reg4 MCR, reg5 LSR, reg6 MSR with addr7 illegal and DLAB-mismatch ignore via monitor [f_rbr_addr0] [f_thr_addr0] [f_ier_addr1] [f_iir_fcr_addr2] [f_lcr_addr3]
3. SAMPLE cg_cross_addr_dlab for addr0/addr1 alias vs addr2-6 normal crossed with DLAB on each completion via monitor [f_dlab_gate_divisor] [f_dlab_gate_normal_blocked] [f_dll_lsb] [f_dlm_msb]
4. SAMPLE cg_dlab_divisor for DLAB state with LSB and MSB byte values including zero and maximum on divisor completions via monitor [f_dll_lsb] [f_dlm_msb]
```

## Completion

1. Done when directed slots plus N controlled transactions all completed with monitor-sampled coverage and DLAB=0 idle cleanup
2. Bound by TEST_TIMEOUT_CYCLES operational limit; timeout is testbench limit not DUT timing

## Questions

1. What are documented legal masks and access types per WISHBONE address for random constraints?
2. What is wb_rst_i polarity and required deassert-to-first-write delay after reset before init and top traffic?
3. What are required wb_sel_i values, owners and tie-offs for 8-bit FIFO-only use, and inactive levels of wb_stb_i and wb_cyc_i that must be driven?
4. What are documented legal data values/masks per writable register (IER enables, LCR line bits, FCR trigger, MCR, THR, divisor LSB/MSB including whether divisor 0 is illegal) for constrained random?
5. What is explicit bus address representation for wb_adr_i pin values (3-bit vs 5-bit) and required handling of addr 7 which is illegal for 8-bit use?

## Essential blockers


## Specification evidence

- `f_rbr_addr0` → `/registers/registers/1` / `CH-f88915355b`
> Receiver Buffer 0 8 R Receiver FIFO output

- `f_thr_addr0` → `/registers/registers/2` / `CH-f88915355b`
> 0 8 W Transmit FIFO input

- `f_dlab_gate_divisor` → `/sections/9/entries/5` / `CH-f88915355b`
> The registers can be accessed when the 7th (DLAB) bit of the Line Control Register is set

- `f_dlab_gate_normal_blocked` → `/sections/9/entries/5` / `CH-f88915355b`
> At this time the above registers at addresses 0-1 can’t be accessed.

- `f_dll_lsb` → `/sections/9/entries/1` / `CH-f88915355b`
> Divisor Latch Byte 1 (LSB) 0 8 RW The LSB of the divisor

- `f_dlm_msb` → `/sections/9/entries/1` / `CH-f88915355b`
> Divisor Latch Byte 2 1 8 RW The MSB of the divisor

- `f_ier_addr1` → `/sections/9/entries/8` / `CH-f88915355b`
> Interrupt Enable 1 8 RW Enable/Mask interrupts

- `f_iir_fcr_addr2` → `/sections/9/entries/8` / `CH-f88915355b`
> Interrupt Identification 2 8 R Get interrupt information
> FIFO Control 2 8 W Control FIFO options

- `f_lcr_addr3` → `/sections/9/entries/8` / `CH-f88915355b`
> Line Control Register 3 8 RW Control connection

- `f_mcr_lsr_msr_addr456` → `/sections/9/entries/0` / `CH-f88915355b`
> Modem Control 4 8 W Controls modem
> Line Status 5 8 R Status information
> Modem Status 6 8 R Modem Status

- `f_div_order_msb_first` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> Set the Divisor Latches, MSB first, LSB next.

- `f_dlab_enable_access` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> Set bit 7 to ‘1’
> to allow access to the Divisor Latches.

- `f_dlab_disable_access` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> Set bit 7 of LCR to ‘0’ to disable access to Divisor Latches.

- `f_reset_div_zero` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The Divisor Latch register is set to 0.

- `f_reset_lcr_8n1` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> The Line Control Register is set to communication of 8 bits of data, no parity, 1
> stop bit.

- `f_reset_ier_disabled` → `/sections/8/entries/1` / `CH-1e2324cfc3`
> All interrupts are disabled in the Interrupt Enable Register.
