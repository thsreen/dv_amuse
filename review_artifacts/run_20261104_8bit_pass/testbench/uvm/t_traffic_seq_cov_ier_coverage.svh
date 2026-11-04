// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_traffic_seq_cov_ier_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_traffic_seq_cov_ier_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_t_traffic_seq_cov_ier_bits;
  covergroup transactions;
    option.per_instance=1;
    t_traffic_seq_cov_ier_bits: coverpoint sampled_t_traffic_seq_cov_ier_bits { bins none={64'h0}; bins rda={64'h1}; bins thre={64'h2}; bins all={64'hf}; }

  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if(observed.address==64'h1) begin
      sampled_t_traffic_seq_cov_ier_bits=(observed.data & 64'hf) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_traffic_seq_cov_ier samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
