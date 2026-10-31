class serial_link_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(serial_link_coverage)
  serial_link_cfg cfg;
  cg_item observed;
  int event_kind, data_class, address_class, frame_bits, parity_mode, stop_bits;
  bit error_seen;
  int unsigned samples;
  covergroup transactions;
    option.per_instance=1;
    cp_operation: coverpoint event_kind { bins receive={3}; bins transmit={4}; }
    cp_data: coverpoint data_class { bins zero={0}; bins maximum={1}; bins representative={2}; }
    cp_address: coverpoint address_class { bins not_register={0}; }
    cp_error: coverpoint error_seen { bins clean={0}; bins error={1}; }
    cp_word: coverpoint frame_bits { bins configured={8}; }
    cp_parity: coverpoint parity_mode { bins configured={0}; }
    cp_stop: coverpoint stop_bits { bins configured={1}; }
    operation_data: cross cp_operation, cp_data;
  endgroup
  function new(string name, uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if (!$cast(observed, tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    event_kind=observed.kind; error_seen=observed.error;
    frame_bits=observed.data_bits; parity_mode=observed.parity_mode; stop_bits=observed.stop_bits;
    data_class=(observed.data==0) ? 0 : ((observed.data & 64'hff)==64'hff) ? 1 : 2;
    address_class=0;


    samples++; transactions.sample();
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("OBSERVED_COVERAGE", $sformatf("serial_link samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
