// Syntax-only macro definitions. NOT a UVM implementation and never used for execution.
`define uvm_object_utils(T)
`define uvm_component_utils(T)
`define uvm_object_utils_begin(T)
`define uvm_object_utils_end
`define uvm_field_int(F, FLAGS)
`define uvm_field_string(F, FLAGS)
`define uvm_fatal(ID, MSG) begin $fatal(1, MSG); end
`define uvm_error(ID, MSG) begin $error(MSG); end
`define uvm_warning(ID, MSG) begin $warning(MSG); end
`define uvm_info(ID, MSG, VERBOSITY) begin $display("%s: %s", ID, MSG); end
