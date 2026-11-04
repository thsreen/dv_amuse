// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class wishbone_slave_interface_cfg extends uvm_object;
  `uvm_object_utils(wishbone_slave_interface_cfg)
  virtual wishbone_slave_interface_if vif;
  bit active = 1;
  bit reset_active = 1;
  int timeout_cycles = 10000;
  int bit_cycles = 2;
  int data_bits = 8;
  int parity_mode = 0;
  int stop_bits = 1;
  function new(string name="wishbone_slave_interface_cfg"); super.new(name); endfunction
endclass
