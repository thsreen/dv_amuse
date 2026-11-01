// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class cg_item extends uvm_sequence_item;
  rand longint unsigned data;
  longint unsigned address;
  longint unsigned mask;
  int kind;
  int cycles;
  string origin;
  bit error;
  int data_bits;
  int parity_mode;
  int stop_bits;
  `uvm_object_utils_begin(cg_item)
    `uvm_field_int(data, UVM_ALL_ON)
    `uvm_field_int(address, UVM_ALL_ON)
    `uvm_field_int(mask, UVM_ALL_ON)
    `uvm_field_int(kind, UVM_ALL_ON)
    `uvm_field_int(cycles, UVM_ALL_ON)
    `uvm_field_string(origin, UVM_ALL_ON)
    `uvm_field_int(error, UVM_ALL_ON)
    `uvm_field_int(data_bits, UVM_ALL_ON)
    `uvm_field_int(parity_mode, UVM_ALL_ON)
    `uvm_field_int(stop_bits, UVM_ALL_ON)
  `uvm_object_utils_end
  function new(string name="cg_item"); super.new(name); endfunction
endclass
