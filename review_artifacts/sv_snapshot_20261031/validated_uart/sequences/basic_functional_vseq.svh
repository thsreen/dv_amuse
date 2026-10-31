class basic_functional_vseq extends uvm_sequence;
  `uvm_object_utils(basic_functional_vseq)
  register_bus_sequencer register_bus_sqr;
  serial_link_sequencer serial_link_sqr;
  function new(string name="basic_functional_vseq"); super.new(name); endfunction
  task body();
    fork
      begin initialize_link seq_0_initialize_link;
        seq_0_initialize_link=initialize_link::type_id::create("seq_0_initialize_link");
        seq_0_initialize_link.start(register_bus_sqr); end
    join
    fork
      begin check_configuration seq_1_check_configuration;
        seq_1_check_configuration=check_configuration::type_id::create("seq_1_check_configuration");
        seq_1_check_configuration.start(register_bus_sqr); end
    join
    fork
      begin transmit_directed seq_2_transmit_directed;
        seq_2_transmit_directed=transmit_directed::type_id::create("seq_2_transmit_directed");
        seq_2_transmit_directed.start(register_bus_sqr); end
    join
    fork
      begin receive_directed seq_3_receive_directed;
        seq_3_receive_directed=receive_directed::type_id::create("seq_3_receive_directed");
        seq_3_receive_directed.start(serial_link_sqr); end
    join
    fork
      begin read_received seq_4_read_received;
        seq_4_read_received=read_received::type_id::create("seq_4_read_received");
        seq_4_read_received.start(register_bus_sqr); end
    join
    begin basic_functional_register_bus_drain drain; drain=basic_functional_register_bus_drain::type_id::create("drain"); drain.start(register_bus_sqr); end
    begin basic_functional_serial_link_drain drain; drain=basic_functional_serial_link_drain::type_id::create("drain"); drain.start(serial_link_sqr); end
  endtask
endclass
