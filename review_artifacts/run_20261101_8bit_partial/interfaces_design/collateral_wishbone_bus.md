# Wishbone Bus collateral infrastructure

WISHBONE slave register access front-end for UART control and data connects interconnect peer to DUT responder via agent collateral_wishbone_bus. Agent drives wb_adr_i wb_sel_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i and observes wb_dat_o wb_ack_o per spec_rtl_relation in 3-bit address 8-bit data mode; wb_clk_i and wb_rst_i are separate units. QUICK_TEST_AUTO_APPROVAL roles and idle_values are test-only infrastructure bindings and never human sign-off; later monitor sampling scoreboard and register map build on this ownership.

## Required actions

- Deploy agent collateral_wishbone_bus owning wb_adr_i wb_sel_i wb_dat_i wb_we_i wb_stb_i wb_cyc_i as drives and wb_dat_o wb_ack_o as observes on uart_top per spec_rtl_relation widths 3_4_8_8_1_1_1_1
- Apply QUICK_TEST_AUTO_APPROVAL roles wb_we_to_wb_we_i wb_stb_to_wb_stb_i wb_cyc_to_wb_cyc_i wb_ack_to_wb_ack_o with idle_values wb_we_i_0 wb_stb_i_0 wb_cyc_i_0 parked deasserted test-only without creating extra owner
- Retain documented 3-bit register-select address and 8-bit data modes for WISHBONE slave register access without adding scoreboard tests coverage or register map

## Completion

- Agent collateral_wishbone_bus drives and observes listed uart_top ports
- Quick-test-only WISHBONE roles and idle_values applied as test-only configuration
- No tie-offs on owned ports and no other interfaces implemented

## Deferred questions

- On which wb_clk_i edge should the later monitor sample wb_adr_i, wb_sel_i, wb_dat_i, wb_we_i, wb_stb_i, wb_cyc_i and observe wb_dat_o, wb_ack_o? Sources define handshake purpose but no sampling edge; needed only for later-phase timing, not scaffold.
- Evidence substituted: f_wb_cyc_i, f_wb_dat_i, f_wb_dat_o, f_wb_stb_i, f_wb_we_i could not be proven from the retrieved sources (Fact must reference a retrieved documented item); the documented facts of this interface are cited instead. Review the choice that cited them.
