class interrupt_output_cfg extends uvm_object;
  `uvm_object_utils(interrupt_output_cfg)
  virtual interrupt_output_if vif;
  bit active = 0;
  bit reset_active = 1;
  int timeout_cycles = 10000;
  int bit_cycles = 2;
  int data_bits = 8;
  int parity_mode = 0;
  int stop_bits = 1;
  function new(string name="interrupt_output_cfg"); super.new(name); endfunction
endclass
