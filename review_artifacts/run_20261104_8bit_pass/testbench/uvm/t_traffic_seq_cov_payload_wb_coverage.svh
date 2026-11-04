// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_traffic_seq_cov_payload_wb_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_traffic_seq_cov_payload_wb_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_t_traffic_seq_cov_wb_data;
  covergroup transactions;
    option.per_instance=1;
    t_traffic_seq_cov_wb_data: coverpoint sampled_t_traffic_seq_cov_wb_data { bins all_zeros={64'h0}; bins all_ones={64'hff}; bins mid={64'h55, 64'haa}; }

  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if(observed.address==64'h0) begin
      sampled_t_traffic_seq_cov_wb_data=(observed.data & 64'hff) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_traffic_seq_cov_payload_wb samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
