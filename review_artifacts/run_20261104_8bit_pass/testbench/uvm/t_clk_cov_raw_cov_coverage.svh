// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_clk_cov_raw_cov_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_clk_cov_raw_cov_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_t_clk_cov_raw_pt;
  covergroup transactions;
    option.per_instance=1;
    t_clk_cov_raw_pt: coverpoint sampled_t_clk_cov_raw_pt { bins t_clk_cov_raw_bin={64'h0}; }

  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if(1) begin
      sampled_t_clk_cov_raw_pt=(observed.data & 64'h0) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_clk_cov_raw_cov samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
