// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_modem_irq_cov_ier_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_modem_irq_cov_ier_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_t_modem_irq_cov_ier_pt;
  covergroup transactions;
    option.per_instance=1;
    t_modem_irq_cov_ier_pt: coverpoint sampled_t_modem_irq_cov_ier_pt { bins disabled={64'h0}; bins enabled={64'h1}; }

  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if(observed.address==64'h1) begin
      sampled_t_modem_irq_cov_ier_pt=(observed.data & 64'h8) >> 3;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_modem_irq_cov_ier samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
