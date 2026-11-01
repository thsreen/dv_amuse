class wishbone_bus_cfg extends uvm_object;
  `uvm_object_utils(wishbone_bus_cfg)
  virtual wishbone_bus_if vif;
  bit active = 1;
  bit reset_active = 1;
  int timeout_cycles = 10000;
  int bit_cycles = 8;
  int data_bits = 8;
  int parity_mode = 0;
  int stop_bits = 1;
  function new(string name="wishbone_bus_cfg"); super.new(name); endfunction
endclass
