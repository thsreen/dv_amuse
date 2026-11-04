// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_irq_baud_mon_cov_int_o_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_irq_baud_mon_cov_int_o_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_t_irq_baud_mon_pt_int_o_toggle;
  covergroup transactions;
    option.per_instance=1;
    t_irq_baud_mon_pt_int_o_toggle: coverpoint sampled_t_irq_baud_mon_pt_int_o_toggle { bins level_0={64'h0}; bins level_1={64'h1}; }

  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if(1) begin
      sampled_t_irq_baud_mon_pt_int_o_toggle=(observed.data & 64'h1) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_irq_baud_mon_cov_int_o samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
