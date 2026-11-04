// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_modem_traffic_cov_uart_rx_seq extends t_traffic_seq_uart_normal_seq;
  `uvm_object_utils(t_modem_traffic_cov_uart_rx_seq)
  `uvm_declare_p_sequencer(uart_serial_data_sequencer)
  function new(string name="t_modem_traffic_cov_uart_rx_seq"); super.new(name); endfunction
  task body();
    cg_item tr;
    super.body();
    repeat(4) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=3; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=p_sequencer.t_modem_traffic_cov_uart_byte;
      finish_item(tr);
    end
  endtask
endclass
