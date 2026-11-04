// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_divisor_cov_rc_divisor_bytes_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_divisor_cov_rc_divisor_bytes_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_cp_divisor_value;
  covergroup transactions;
    option.per_instance=1;
    cp_divisor_value: coverpoint sampled_cp_divisor_value { bins lsb_zero_0x00={64'h0}; bins lsb_mid_0x01_0xFE={64'h1, 64'h40, 64'ha0, 64'hfe}; bins lsb_max_0xFF={64'hff}; bins msb_zero_0x00={64'h0}; bins msb_mid_0x01_0xFE={64'h1, 64'h40, 64'ha0, 64'hfe}; bins msb_max_0xFF={64'hff}; bins combined_zero_disables={64'h0}; bins combined_nonzero_enables={64'h1, 64'h40, 64'ha0, 64'hff}; }

  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if((observed.kind==1)) begin
      sampled_cp_divisor_value=(observed.data & 64'hff) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_divisor_cov_rc_divisor_bytes samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
