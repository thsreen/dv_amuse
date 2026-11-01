class wishbone_bus_sequencer extends uvm_sequencer #(cg_item);
  `uvm_component_utils(wishbone_bus_sequencer)
  wishbone_bus_cfg cfg;

  function new(string name, uvm_component parent); super.new(name, parent); endfunction
endclass
