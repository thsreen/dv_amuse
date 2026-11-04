// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_uart_mon_uart_rx_seq extends uvm_sequence #(cg_item);
  `uvm_object_utils(t_uart_mon_uart_rx_seq)
  `uvm_declare_p_sequencer(uart_serial_data_sequencer)
  function new(string name="t_uart_mon_uart_rx_seq"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=3; tr.address=64'h0; tr.mask=64'hff; tr.cycles=16;
      tr.data=p_sequencer.t_uart_mon_uart_byte;
      finish_item(tr);
    end
  endtask
endclass
