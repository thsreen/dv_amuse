// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class serial_link_sequencer extends uvm_sequencer #(cg_item);
  `uvm_component_utils(serial_link_sequencer)
  serial_link_cfg cfg;

  function new(string name, uvm_component parent); super.new(name, parent); endfunction
endclass
