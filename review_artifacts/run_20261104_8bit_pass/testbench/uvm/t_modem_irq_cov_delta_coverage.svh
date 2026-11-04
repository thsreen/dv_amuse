// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_modem_irq_cov_delta_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_modem_irq_cov_delta_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_t_modem_irq_cov_delta_pt;
  covergroup transactions;
    option.per_instance=1;
    t_modem_irq_cov_delta_pt: coverpoint sampled_t_modem_irq_cov_delta_pt { bins dcts={64'h1}; bins ddsr={64'h2}; bins teri={64'h4}; bins ddcd={64'h8}; }

  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if(observed.address==64'h6) begin
      sampled_t_modem_irq_cov_delta_pt=(observed.data & 64'hf) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_modem_irq_cov_delta samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
