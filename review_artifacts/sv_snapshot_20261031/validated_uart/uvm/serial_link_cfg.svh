class serial_link_cfg extends uvm_object;
  `uvm_object_utils(serial_link_cfg)
  virtual serial_link_if vif;
  bit active = 1;
  bit reset_active = 1;
  int timeout_cycles = 10000;
  int bit_cycles = 32;
  int data_bits = 8;
  int parity_mode = 0;
  int stop_bits = 1;
  function new(string name="serial_link_cfg"); super.new(name); endfunction
endclass
