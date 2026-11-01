class modem_control_if_sequencer extends uvm_sequencer #(cg_item);
  `uvm_component_utils(modem_control_if_sequencer)
  modem_control_if_cfg cfg;

  function new(string name, uvm_component parent); super.new(name, parent); endfunction
endclass
