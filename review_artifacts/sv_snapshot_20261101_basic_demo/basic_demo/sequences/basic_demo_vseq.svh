// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class basic_demo_vseq extends uvm_sequence;
  `uvm_object_utils(basic_demo_vseq)
  register_bus_sequencer register_bus_sqr;
  serial_link_sequencer serial_link_sqr;
  function new(string name="basic_demo_vseq"); super.new(name); endfunction
  task body();
    fork
      begin configure_link seq_0_configure_link;
        seq_0_configure_link=configure_link::type_id::create("seq_0_configure_link");
        seq_0_configure_link.start(register_bus_sqr); end
    join
    fork
      begin read_back_line_control seq_1_read_back_line_control;
        seq_1_read_back_line_control=read_back_line_control::type_id::create("seq_1_read_back_line_control");
        seq_1_read_back_line_control.start(register_bus_sqr); end
    join
    fork
      begin send_one_packet seq_2_send_one_packet;
        seq_2_send_one_packet=send_one_packet::type_id::create("seq_2_send_one_packet");
        seq_2_send_one_packet.start(register_bus_sqr); end
    join
    fork
      begin receive_one_packet seq_3_receive_one_packet;
        seq_3_receive_one_packet=receive_one_packet::type_id::create("seq_3_receive_one_packet");
        seq_3_receive_one_packet.start(serial_link_sqr); end
    join
    fork
      begin collect_received_packet seq_4_collect_received_packet;
        seq_4_collect_received_packet=collect_received_packet::type_id::create("seq_4_collect_received_packet");
        seq_4_collect_received_packet.start(register_bus_sqr); end
    join
    begin basic_demo_register_bus_drain drain; drain=basic_demo_register_bus_drain::type_id::create("drain"); drain.start(register_bus_sqr); end
    begin basic_demo_serial_link_drain drain; drain=basic_demo_serial_link_drain::type_id::create("drain"); drain.start(serial_link_sqr); end
  endtask
endclass
