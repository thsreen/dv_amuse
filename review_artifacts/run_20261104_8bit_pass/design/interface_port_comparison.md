# Specification / RTL port comparison

Status: **PASS**

Independent validation: **PASS** ([report](interface_port_validation.md))

| Specification | RTL | Spec direction | RTL direction | Spec width | RTL width | Status | Issues |
|---|---|---|---|---|---|---|---|
| CLK | wb_clk_i | input | input | 1 | 1 | PASS |  |
| WB_RST_I | wb_rst_i | input | input | 1 | 1 | PASS |  |
| WB_ADDR_I | wb_adr_i | input | input | 3 | 3 | PASS |  |
| WB_SEL_I | wb_sel_i | input | input | 4 | 4 | PASS |  |
| WB_DAT_I | wb_dat_i | input | input | 8 | 8 | PASS |  |
| WB_DAT_O | wb_dat_o | output | output | 8 | 8 | PASS |  |
| WB_WE_I | wb_we_i | input | input | 1 | 1 | PASS |  |
| WB_STB_I | wb_stb_i | input | input | 1 | 1 | PASS |  |
| WB_CYC_I | wb_cyc_i | input | input | 1 | 1 | PASS |  |
| WB_ACK_O | wb_ack_o | output | output | 1 | 1 | PASS |  |
| INT_O | int_o | output | output | 1 | 1 | PASS |  |
| BAUD_O | None |  |  |  |  | INACTIVE_REVIEWED | Documented conditional output is disabled in the selected RTL configuration. |
| STX_PAD_O | stx_pad_o | output | output | 1 | 1 | PASS |  |
| SRX_PAD_I | srx_pad_i | input | input | 1 | 1 | PASS |  |
| RTS_PAD_O | rts_pad_o | output | output | 1 | 1 | PASS |  |
| DTR_PAD_O | dtr_pad_o | output | output | 1 | 1 | PASS |  |
| CTS_PAD_I | cts_pad_i | input | input | 1 | 1 | PASS |  |
| DSR_PAD_I | dsr_pad_i | input | input | 1 | 1 | PASS |  |
| RI_PAD_I | ri_pad_i | input | input | 1 | 1 | PASS |  |
| DCD_PAD_I | dcd_pad_i | input | input | 1 | 1 | PASS |  |


## Specification and RTL relationship

Specification defines behavior; RTL defines physical connectivity. Alignment does not promote inferred semantics.

### CLK → wb_clk_i

- Match: reviewed_alias; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-63ad4d61a5
- Description: Block’s clock input
- Active level: unknown (documented: False)

> CLK 1 Input Block’s clock input

### WB_RST_I → wb_rst_i

- Match: normalized_name; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-63ad4d61a5
- Description: Asynchronous Reset
- Active level: unknown (documented: False)

> WB_RST_I 1 Input Asynchronous Reset

### WB_ADDR_I → wb_adr_i

- Match: reviewed_alias; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-63ad4d61a5
- Description: Used for register selection
- Active level: not_applicable (documented: False)

> WB_ADDR_I 5 or 3 Input Used for register selection

### WB_SEL_I → wb_sel_i

- Match: normalized_name; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-63ad4d61a5
- Description: Select signal
- Active level: unknown (documented: False)

> WB_SEL_I 4 Input Select signal

### WB_DAT_I → wb_dat_i

- Match: reviewed_alias; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-63ad4d61a5
- Description: Data input
- Active level: not_applicable (documented: False)

> WB_DAT_I 32 or 8 Input Data input

### WB_DAT_O → wb_dat_o

- Match: reviewed_alias; testbench responsibility: observe.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-63ad4d61a5
- Description: Data output
- Active level: not_applicable (documented: False)

> WB_DAT_O 32 or 8 Output Data output

### WB_WE_I → wb_we_i

- Match: normalized_name; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-63ad4d61a5
- Description: Write or read cycle selection
- Active level: unknown (documented: False)

> WB_WE_I 1 Input Write or read cycle selection

### WB_STB_I → wb_stb_i

- Match: normalized_name; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-63ad4d61a5
- Description: Specifies transfer cycle
- Active level: unknown (documented: False)

> WB_STB_I 1 Input Specifies transfer cycle

### WB_CYC_I → wb_cyc_i

- Match: normalized_name; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-63ad4d61a5
- Description: A bus cycle is in progress
- Active level: unknown (documented: False)

> WB_CYC_I 1 Input A bus cycle is in progress

### WB_ACK_O → wb_ack_o

- Match: normalized_name; testbench responsibility: observe.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-63ad4d61a5
- Description: Acknowledge of a transfer
- Active level: unknown (documented: False)

> WB_ACK_O 1 Output Acknowledge of a transfer

### INT_O → int_o

- Match: normalized_name; testbench responsibility: observe.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-8c2c8e9408
- Description: Interrupt output
- Active level: unknown (documented: False)

> INT_O 1 Output Interrupt output

### BAUD_O → None

- Match: unresolved; testbench responsibility: unresolved.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-8c2c8e9408
- Description: Optional baud rate output signal. The signal here is the 16 x actual baud rate.
- Active level: unknown (documented: False)

> BAUD_O 1 Output Optional baud rate output signal.
> The signal here is the 16 x actual baud rate.
> It is enabled if UART_HAS_BAUDRATE_OUTPUT
> is defined

### STX_PAD_O → stx_pad_o

- Match: normalized_name; testbench responsibility: observe.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-98be4510fb
- Description: The serial output signal
- Active level: not_applicable (documented: False)

> STX_PAD_O 1 Output The serial output signal

### SRX_PAD_I → srx_pad_i

- Match: normalized_name; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-98be4510fb
- Description: The serial input signal
- Active level: not_applicable (documented: False)

> SRX_PAD_I 1 Input The serial input signal

### RTS_PAD_O → rts_pad_o

- Match: normalized_name; testbench responsibility: observe.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-98be4510fb
- Description: Request To Send
- Active level: unknown (documented: False)

> RTS_PAD_O 1 Output Request To Send

### DTR_PAD_O → dtr_pad_o

- Match: normalized_name; testbench responsibility: observe.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-98be4510fb
- Description: Data Terminal Ready
- Active level: unknown (documented: False)

> DTR_PAD_O 1 Output Data Terminal Ready

### CTS_PAD_I → cts_pad_i

- Match: normalized_name; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-98be4510fb
- Description: Clear To Send
- Active level: unknown (documented: False)

> CTS_PAD_I 1 Input Clear To Send

### DSR_PAD_I → dsr_pad_i

- Match: normalized_name; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-98be4510fb
- Description: Data Set Ready
- Active level: unknown (documented: False)

> DSR_PAD_I 1 Input Data Set Ready

### RI_PAD_I → ri_pad_i

- Match: normalized_name; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-98be4510fb
- Description: Ring Indicator
- Active level: unknown (documented: False)

> RI_PAD_I 1 Input Ring Indicator

### DCD_PAD_I → dcd_pad_i

- Match: normalized_name; testbench responsibility: drive.
- Specification: uart16550/doc/UART_spec.pdf [6, 6] / CH-98be4510fb
- Description: Data Carrier Detect
- Active level: unknown (documented: False)

> DCD_PAD_I 1 Input Data Carrier Detect

### Interface group: wishbone_slave_interface

- **name**: wishbone_slave_interface (INFERRED)
- **category**: bus (DOCUMENTED)
- **function**: WISHBONE SoC bus slave interface for register access to UART (DOCUMENTED)
- **protocol**: WISHBONE (DOCUMENTED)
- **dut_role**: responder (INFERRED)
- **connected_to**: WISHBONE bus (DOCUMENTED)
- **peer_type**: interconnect (INFERRED)
- **is_sideband**: False (INFERRED)
- Evidence and classification: `/interfaces/groups/0/property_evidence` (retained in JSON)

### Interface group: system_clock

- **name**: system_clock (INFERRED)
- **category**: clock (DOCUMENTED)
- **function**: Block clock input for UART core logic (DOCUMENTED)
- **protocol**:  (DOCUMENTED)
- **dut_role**: sink (DOCUMENTED)
- **connected_to**: WISHBONE bus (DOCUMENTED)
- **peer_type**: clock_generator (INFERRED)
- **is_sideband**: False (INFERRED)
- Evidence and classification: `/interfaces/groups/1/property_evidence` (retained in JSON)

### Interface group: wishbone_reset

- **name**: wishbone_reset (INFERRED)
- **category**: reset (DOCUMENTED)
- **function**: Asynchronous reset input for UART core (DOCUMENTED)
- **protocol**:  (DOCUMENTED)
- **dut_role**: sink (DOCUMENTED)
- **connected_to**:  (DOCUMENTED)
- **peer_type**: reset_controller (INFERRED)
- **is_sideband**: False (INFERRED)
- Evidence and classification: `/interfaces/groups/2/property_evidence` (retained in JSON)

### Interface group: interrupt_output

- **name**: interrupt_output (INFERRED)
- **category**: interrupt (DOCUMENTED)
- **function**: Interrupt output to signal UART events to system (DOCUMENTED)
- **protocol**:  (DOCUMENTED)
- **dut_role**: source (DOCUMENTED)
- **connected_to**:  (DOCUMENTED)
- **peer_type**: interrupt_controller (INFERRED)
- **is_sideband**: True (INFERRED)
- Evidence and classification: `/interfaces/groups/3/property_evidence` (retained in JSON)

### Interface group: uart_serial_data

- **name**: uart_serial_data (INFERRED)
- **category**: serial_data (DOCUMENTED)
- **function**: UART serial transmit and receive data lines (DOCUMENTED)
- **protocol**: RS232 (DOCUMENTED)
- **dut_role**: bidirectional (DOCUMENTED)
- **connected_to**: modem or other external devices (DOCUMENTED)
- **peer_type**: external_device (DOCUMENTED)
- **is_sideband**: False (INFERRED)
- Evidence and classification: `/interfaces/groups/4/property_evidence` (retained in JSON)

### Interface group: modem_control

- **name**: modem_control (INFERRED)
- **category**: flow_control (DOCUMENTED)
- **function**: Modem control and status handshake signals (RTS/CTS/DTR/DSR/RI/DCD) (DOCUMENTED)
- **protocol**:  (DOCUMENTED)
- **dut_role**: bidirectional (INFERRED)
- **connected_to**: modem (DOCUMENTED)
- **peer_type**: external_device (DOCUMENTED)
- **is_sideband**: True (INFERRED)
- Evidence and classification: `/interfaces/groups/5/property_evidence` (retained in JSON)

### Interface group: baud_rate_output

- **name**: baud_rate_output (INFERRED)
- **category**: clock (INFERRED)
- **function**: Optional 16x baud rate tick output (DOCUMENTED)
- **protocol**:  (DOCUMENTED)
- **dut_role**: source (DOCUMENTED)
- **connected_to**:  (DOCUMENTED)
- **peer_type**: unknown (DOCUMENTED)
- **is_sideband**: True (INFERRED)
- Evidence and classification: `/interfaces/groups/6/property_evidence` (retained in JSON)

