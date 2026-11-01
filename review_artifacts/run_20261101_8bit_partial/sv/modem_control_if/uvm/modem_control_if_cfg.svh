class modem_control_if_cfg extends uvm_object;
  `uvm_object_utils(modem_control_if_cfg)
  virtual modem_control_if_if vif;
  bit active = 1;
  bit reset_active = 1;
  int timeout_cycles = 10000;
  int bit_cycles = 16;
  int data_bits = 8;
  int parity_mode = 0;
  int stop_bits = 1;
  function new(string name="modem_control_if_cfg"); super.new(name); endfunction
endclass
