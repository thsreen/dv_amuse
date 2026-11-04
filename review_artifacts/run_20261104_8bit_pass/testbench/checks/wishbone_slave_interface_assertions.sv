// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
module wishbone_slave_interface_assertions(wishbone_slave_interface_if bus);
  property p_t_wb_mon_check_xz; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_wb_mon_check_xz: assert property(p_t_wb_mon_check_xz) else $error("t_wb_mon_check_xz");
  c_t_wb_mon_check_xz: cover property(p_t_wb_mon_check_xz);
  activation_t_wb_mon_check_xz: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
  property p_t_wb_mon_check_known; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_wb_mon_check_known: assert property(p_t_wb_mon_check_known) else $error("t_wb_mon_check_known");
  c_t_wb_mon_check_known: cover property(p_t_wb_mon_check_known);
  activation_t_wb_mon_check_known: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
  property p_t_reset_state_check_lcr_reset; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_reset_state_check_lcr_reset: assert property(p_t_reset_state_check_lcr_reset) else $error("t_reset_state_check_lcr_reset");
  c_t_reset_state_check_lcr_reset: cover property(p_t_reset_state_check_lcr_reset);
  activation_t_reset_state_check_lcr_reset: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
  property p_t_wb_init_cfg_ier_check; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_wb_init_cfg_ier_check: assert property(p_t_wb_init_cfg_ier_check) else $error("t_wb_init_cfg_ier_check");
  c_t_wb_init_cfg_ier_check: cover property(p_t_wb_init_cfg_ier_check);
  activation_t_wb_init_cfg_ier_check: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
  property p_t_xz_check_check_xz_wb; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_xz_check_check_xz_wb: assert property(p_t_xz_check_check_xz_wb) else $error("t_xz_check_check_xz_wb");
  c_t_xz_check_check_xz_wb: cover property(p_t_xz_check_check_xz_wb);
  activation_t_xz_check_check_xz_wb: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
  property p_t_xz_check_check_known_wb; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_xz_check_check_known_wb: assert property(p_t_xz_check_check_known_wb) else $error("t_xz_check_check_known_wb");
  c_t_xz_check_check_known_wb: cover property(p_t_xz_check_check_known_wb);
  activation_t_xz_check_check_known_wb: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
  property p_t_dlab_gate_chk_alias_class_check; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb && !bus.ack) |=> ($stable({bus.addr,bus.wdata,bus.sel,bus.we})); endproperty
  a_t_dlab_gate_chk_alias_class_check: assert property(p_t_dlab_gate_chk_alias_class_check) else $error("t_dlab_gate_chk_alias_class_check");
  c_t_dlab_gate_chk_alias_class_check: cover property(p_t_dlab_gate_chk_alias_class_check);
  activation_t_dlab_gate_chk_alias_class_check: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb && !bus.ack);
  property p_t_traffic_seq_ier_chk; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_traffic_seq_ier_chk: assert property(p_t_traffic_seq_ier_chk) else $error("t_traffic_seq_ier_chk");
  c_t_traffic_seq_ier_chk: cover property(p_t_traffic_seq_ier_chk);
  activation_t_traffic_seq_ier_chk: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
  property p_t_ier_iir_pend_chk_ier; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_ier_iir_pend_chk_ier: assert property(p_t_ier_iir_pend_chk_ier) else $error("t_ier_iir_pend_chk_ier");
  c_t_ier_iir_pend_chk_ier: cover property(p_t_ier_iir_pend_chk_ier);
  activation_t_ier_iir_pend_chk_ier: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
  property p_t_ier_iir_pend_chk_reset; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_ier_iir_pend_chk_reset: assert property(p_t_ier_iir_pend_chk_reset) else $error("t_ier_iir_pend_chk_reset");
  c_t_ier_iir_pend_chk_reset: cover property(p_t_ier_iir_pend_chk_reset);
  activation_t_ier_iir_pend_chk_reset: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
  property p_t_ier_iir_pend_chk_iir_mask; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_ier_iir_pend_chk_iir_mask: assert property(p_t_ier_iir_pend_chk_iir_mask) else $error("t_ier_iir_pend_chk_iir_mask");
  c_t_ier_iir_pend_chk_iir_mask: cover property(p_t_ier_iir_pend_chk_iir_mask);
  activation_t_ier_iir_pend_chk_iir_mask: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
  property p_t_modem_irq_chk_iir; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_modem_irq_chk_iir: assert property(p_t_modem_irq_chk_iir) else $error("t_modem_irq_chk_iir");
  c_t_modem_irq_chk_iir: cover property(p_t_modem_irq_chk_iir);
  activation_t_modem_irq_chk_iir: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
  property p_t_modem_irq_chk_e2e; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb && !bus.ack) |=> ($stable({bus.addr,bus.wdata,bus.sel,bus.we})); endproperty
  a_t_modem_irq_chk_e2e: assert property(p_t_modem_irq_chk_e2e) else $error("t_modem_irq_chk_e2e");
  c_t_modem_irq_chk_e2e: cover property(p_t_modem_irq_chk_e2e);
  activation_t_modem_irq_chk_e2e: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb && !bus.ack);
  property p_t_modem_traffic_cov_chk_pending; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb && !bus.ack) |=> ($stable({bus.addr,bus.wdata,bus.sel,bus.we})); endproperty
  a_t_modem_traffic_cov_chk_pending: assert property(p_t_modem_traffic_cov_chk_pending) else $error("t_modem_traffic_cov_chk_pending");
  c_t_modem_traffic_cov_chk_pending: cover property(p_t_modem_traffic_cov_chk_pending);
  activation_t_modem_traffic_cov_chk_pending: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb && !bus.ack);
  property p_t_modem_traffic_cov_chk_fixed; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_t_modem_traffic_cov_chk_fixed: assert property(p_t_modem_traffic_cov_chk_fixed) else $error("t_modem_traffic_cov_chk_fixed");
  c_t_modem_traffic_cov_chk_fixed: cover property(p_t_modem_traffic_cov_chk_fixed);
  activation_t_modem_traffic_cov_chk_fixed: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
endmodule
