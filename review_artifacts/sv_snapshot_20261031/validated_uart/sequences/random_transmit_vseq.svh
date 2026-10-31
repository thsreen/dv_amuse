class random_transmit_vseq extends uvm_sequence;
  `uvm_object_utils(random_transmit_vseq)
  register_bus_sequencer register_bus_sqr;
  serial_link_sequencer serial_link_sqr;
  function new(string name="random_transmit_vseq"); super.new(name); endfunction
  task body();
    fork
      begin initialize_link seq_0_initialize_link;
        seq_0_initialize_link=initialize_link::type_id::create("seq_0_initialize_link");
        seq_0_initialize_link.start(register_bus_sqr); end
    join
    fork
      begin transmit_random seq_1_transmit_random;
        seq_1_transmit_random=transmit_random::type_id::create("seq_1_transmit_random");
        seq_1_transmit_random.start(register_bus_sqr); end
    join
    begin random_transmit_register_bus_drain drain; drain=random_transmit_register_bus_drain::type_id::create("drain"); drain.start(register_bus_sqr); end
    begin random_transmit_serial_link_drain drain; drain=random_transmit_serial_link_drain::type_id::create("drain"); drain.start(serial_link_sqr); end
  endtask
endclass
