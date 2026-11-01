// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class register_bus_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(register_bus_coverage)
  register_bus_cfg cfg;
  cg_item observed;
  int event_kind, data_class, address_class, frame_bits, parity_mode, stop_bits;
  bit error_seen;
  int unsigned samples;
  covergroup transactions;
    option.per_instance=1;
    cp_operation: coverpoint event_kind { bins writes={1}; bins reads={2}; }
    cp_data: coverpoint data_class { bins zero={0}; bins maximum={1}; bins representative={2}; }
    cp_address: coverpoint address_class { bins line_control={1};
bins data_or_divisor_low={2};
bins interrupt_enable_or_divisor_high={3};
bins fifo_control={4}; }
    cp_error: coverpoint error_seen { bins clean={0}; bins error={1}; }
    cp_word: coverpoint frame_bits { bins configured={8}; }

    operation_data: cross cp_operation, cp_data;
  endgroup
  function new(string name, uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if (!$cast(observed, tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    event_kind=observed.kind; error_seen=observed.error;
    frame_bits=observed.data_bits; parity_mode=observed.parity_mode; stop_bits=observed.stop_bits;
    data_class=(observed.data==0) ? 0 : ((observed.data & 64'hff)==64'hff) ? 1 : 2;
    address_class=0;
    if(observed.address==64'h3) address_class=1;
    if(observed.address==64'h0) address_class=2;
    if(observed.address==64'h1) address_class=3;
    if(observed.address==64'h2) address_class=4;

    samples++; transactions.sample();
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("OBSERVED_COVERAGE", $sformatf("register_bus samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
