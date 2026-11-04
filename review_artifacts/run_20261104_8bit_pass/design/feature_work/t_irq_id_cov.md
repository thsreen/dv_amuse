# Interrupt ID coverage

Work package: `t_irq_id_cov` · coverage · NEEDS_REVIEW

## Dependent features

- `t_irq_baud_mon`: pending priority coverage needs INT_O IIR observation

## Independent features

`t_addr_dlab_cov`, `t_chip_reset`, `t_clk_cov`, `t_divisor_cov`, `t_dlab_gate_chk`, `t_e2e_arch`, `t_ier_iir_pend`, `t_iir_prio_fixed`, `t_irq_err_chk`, `t_line_err_cov`, `t_lsr_status`, `t_modem_irq`, `t_modem_traffic_cov`, `t_reset_state`, `t_top_virtual`, `t_traffic_seq`, `t_uart_mon`, `t_wb_init_cfg`, `t_wb_mon`, `t_wb_reg_cov`, `t_wb_scoreboard`, `t_wb_top_seq`, `t_xz_check`

_Independent for planning/code generation; this does not authorize concurrent DUT stimulus._

## Understanding

Cover IIR bit0 pending flag, bits3-1 priority codes for five sources, and fixed compatibility bits sampled on IIR reads.

## Preconditions

1. IIR accessible as 8-bit read-only at bus pin value wb_adr_i==2 via wishbone_slave_interface with normal registers selected
2. Single UART instance with clock edges available for sampling and reset released from C1h state
3. Owning traffic sequences capable of producing RLS RDA Timeout THRE and Modem pending states executed by their agents
4. Passive observation only with no driving of IIR or int_o

## Stimulus pseudocode

```text
```

## Check pseudocode

```text
```

## Coverage pseudocode

```text
1. WAIT for Wishbone read completion to address 2 observed via wishbone_slave_interface on clock edge
2. SAMPLE cp_iir_pending from bit0: IF bit0==0 THEN bin pending_0 ELSE IF bit0==1 THEN bin no_pending_1
3. SAMPLE cp_iir_code from bits 3-1: bins code_011_rls and code_010_rda and code_110_timeout and code_001_thre and code_000_modem; illegal codes 100_101_111 must never occur
4. SAMPLE cp_iir_fixed from bits 7-6 and 5-4: IF bits7-6==11 THEN bin fixed_76_11; IF bits5-4==00 THEN bin fixed_54_00; any other fixed bits illegal
5. FOR each IIR read REPEAT sampling until all legal pending and code and fixed bins are hit
```

## Completion

1. End collection after owning traffic sequences complete plus drain_cycles to flush pending IIR read events
2. Abort on request_timeout_cycles operational limit; timeout is testbench limit not DUT timing

## Questions


## Essential blockers


## Specification evidence

- `f_pending` → `/registers/registers/6/fields/0` / `CH-f91cbf1c05`
> Bit 0 indicates that an interrupt is pending when it’s logic ‘0’. When it’s ‘1’ – no interrupt
> is pending.

- `f_highest` → `/sections/8/entries/4` / `CH-f91cbf1c05`
> The IIR enables the programmer to retrieve what is the current highest priority pending
> interrupt.

- `f_rls` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Parity, Overrun or Framing
> errors or Break Interrupt
> Reading the Line
> Status Register

- `f_rda` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> FIFO trigger level reached FIFO drops below
> trigger level

- `f_timeout` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> There’s at least 1 character
> in the FIFO but no character
> has been input to the FIFO
> or read from it for the last 4
> Char times.
> Reading from the
> FIFO (Receiver
> Buffer Register)

- `f_thre` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> Transmitter Holding
> Register Empty
> Writing to the
> Transmitter Holding
> Register or reading
> IIR.

- `f_modem` → `/registers/registers/6/fields/1` / `CH-f91cbf1c05`
> 0 0 0 4 th Modem Status CTS, DSR, RI or DCD. Reading the Modem
> status register.

- `f_fixed45` → `/sections/8/entries/5` / `CH-f91cbf1c05`
> Bits 4 and 5: Logic ‘0’.

- `f_fixed67` → `/sections/8/entries/5` / `CH-f91cbf1c05`
> Bits 6 and 7: Logic ‘1’ for compatibility reason.

- `f_reset` → `/registers/registers/6` / `CH-f91cbf1c05`
> Reset Value: C1h

- `f_addr` → `/registers/registers/6` / `CH-f88915355b`
> Interrupt Identification 2 8 R Get interrupt information

- `f_agent` → `/sections/4/strategy/agents/3` / `CH-d62a4ba2db`
> The core requires one interrupt.

- `f_cg` → `/sections/9/entries/2` / `CH-f91cbf1c05`
> The IIR enables the programmer to retrieve what is the current highest priority pending
> interrupt.
