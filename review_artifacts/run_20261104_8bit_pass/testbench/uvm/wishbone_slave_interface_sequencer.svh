// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class wishbone_slave_interface_sequencer extends uvm_sequencer #(cg_item);
  `uvm_component_utils(wishbone_slave_interface_sequencer)
  wishbone_slave_interface_cfg cfg;
  bit [7:0] t_wb_init_cfg_div_msb=64'h0;
  bit [7:0] t_wb_init_cfg_div_lsb=64'h1;
  bit [7:0] t_wb_init_cfg_fcr_byte=64'hc0;
  bit [7:0] t_wb_init_cfg_ier_byte=64'h0;
  bit [7:0] t_wb_init_cfg_lcr_dlab1=64'h83;
  bit [7:0] t_wb_init_cfg_lcr_dlab0=64'h3;
  bit [7:0] t_divisor_cov_mid_low=64'h40;
  bit [7:0] t_divisor_cov_mid_high=64'ha0;
  bit [7:0] t_dlab_gate_chk_lcr_dlab1=64'h83;
  bit [7:0] t_dlab_gate_chk_lcr_dlab0=64'h3;
  bit [7:0] t_dlab_gate_chk_div_lsb=64'h34;
  bit [7:0] t_dlab_gate_chk_div_msb=64'h12;
  bit [7:0] t_dlab_gate_chk_ier_pat=64'hf;
  bit [7:0] t_dlab_gate_chk_ier_pat2=64'h5;
  bit [7:0] t_traffic_seq_ier_byte=64'h0;
  bit [7:0] t_traffic_seq_payload=64'h0;
  bit [7:0] t_traffic_seq_mcr_byte=64'h10;
  bit [7:0] t_uart_mon_div_lsb=64'h1;
  bit [7:0] t_uart_mon_div_msb=64'h0;
  bit [7:0] t_uart_mon_lcr_dlab1=64'h83;
  bit [7:0] t_uart_mon_lcr_dlab0=64'h3;
  bit [2:0] t_wb_top_seq_addr=64'h0;
  bit [7:0] t_wb_top_seq_wdata=64'h0;
  bit [7:0] t_wb_top_seq_lcr_dlab0=64'h3;
  bit [7:0] t_addr_dlab_cov_lcr_dlab1=64'h80;
  bit [7:0] t_addr_dlab_cov_lcr_dlab0=64'h0;
  bit [7:0] t_addr_dlab_cov_fcr_byte=64'h0;
  bit [7:0] t_addr_dlab_cov_mcr_byte=64'h0;
  bit [7:0] t_addr_dlab_cov_payload=64'h0;
  bit [7:0] t_ier_iir_pend_ier_en=64'h0;
  bit [7:0] t_ier_iir_pend_lcr_dlab0=64'h3;
  bit [7:0] t_modem_irq_ier_dis=64'h0;
  bit [7:0] t_modem_irq_ier_en=64'h8;
  bit [7:0] t_modem_traffic_cov_ier_en=64'h8;
  bit [7:0] t_modem_traffic_cov_payload=64'h55;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
endclass
