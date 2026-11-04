// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class quick_basic_vseq extends uvm_sequence;
  `uvm_object_utils(quick_basic_vseq)
  uart_serial_data_sequencer uart_serial_data_sqr;
  modem_control_if_sequencer modem_control_if_sqr;
  wishbone_slave_interface_sequencer wishbone_slave_interface_sqr;
  function new(string name="quick_basic_vseq"); super.new(name); endfunction
  task body();
    fork
      begin quick_basic_setup seq_0_quick_basic_setup;
        seq_0_quick_basic_setup=quick_basic_setup::type_id::create("seq_0_quick_basic_setup");
        seq_0_quick_basic_setup.start(wishbone_slave_interface_sqr); end
    join
    fork
      begin quick_basic_write seq_1_quick_basic_write;
        seq_1_quick_basic_write=quick_basic_write::type_id::create("seq_1_quick_basic_write");
        seq_1_quick_basic_write.start(wishbone_slave_interface_sqr); end
    join
    fork
      begin quick_basic_send seq_2_quick_basic_send;
        seq_2_quick_basic_send=quick_basic_send::type_id::create("seq_2_quick_basic_send");
        seq_2_quick_basic_send.start(uart_serial_data_sqr); end
    join
    fork
      begin quick_basic_read seq_3_quick_basic_read;
        seq_3_quick_basic_read=quick_basic_read::type_id::create("seq_3_quick_basic_read");
        seq_3_quick_basic_read.start(wishbone_slave_interface_sqr); end
    join
    begin quick_basic_uart_serial_data_drain drain; drain=quick_basic_uart_serial_data_drain::type_id::create("drain"); drain.start(uart_serial_data_sqr); end
    begin quick_basic_modem_control_if_drain drain; drain=quick_basic_modem_control_if_drain::type_id::create("drain"); drain.start(modem_control_if_sqr); end
    begin quick_basic_wishbone_slave_interface_drain drain; drain=quick_basic_wishbone_slave_interface_drain::type_id::create("drain"); drain.start(wishbone_slave_interface_sqr); end
  endtask
endclass
