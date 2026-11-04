// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class modem_control_if_sequencer extends uvm_sequencer #(cg_item);
  `uvm_component_utils(modem_control_if_sequencer)
  modem_control_if_cfg cfg;
  bit [7:0] t_traffic_seq_modem_lvl=64'h0;
  bit [7:0] t_modem_traffic_cov_modem_lvl=64'h0;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
endclass
