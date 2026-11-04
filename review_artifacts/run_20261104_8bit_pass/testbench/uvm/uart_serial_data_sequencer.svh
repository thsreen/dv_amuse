// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class uart_serial_data_sequencer extends uvm_sequencer #(cg_item);
  `uvm_component_utils(uart_serial_data_sequencer)
  uart_serial_data_cfg cfg;
  bit [7:0] t_traffic_seq_uart_byte=64'h0;
  bit [7:0] t_uart_mon_uart_byte=64'h55;
  bit [7:0] t_modem_traffic_cov_uart_byte=64'h55;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
endclass
