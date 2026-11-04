class wishbone_slave_interface_sequencer extends uvm_sequencer #(cg_item);
  `uvm_component_utils(wishbone_slave_interface_sequencer)
  wishbone_slave_interface_cfg cfg;

  function new(string name, uvm_component parent); super.new(name, parent); endfunction
endclass
