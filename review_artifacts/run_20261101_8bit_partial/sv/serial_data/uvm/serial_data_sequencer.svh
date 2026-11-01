class serial_data_sequencer extends uvm_sequencer #(cg_item);
  `uvm_component_utils(serial_data_sequencer)
  serial_data_cfg cfg;

  function new(string name, uvm_component parent); super.new(name, parent); endfunction
endclass
