// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_irq_id_cov_cg_iir_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_irq_id_cov_cg_iir_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_cp_iir_pending;
  longint unsigned sampled_cp_iir_code;
  longint unsigned sampled_cp_iir_fixed_76;
  longint unsigned sampled_cp_iir_fixed_54;
  covergroup transactions;
    option.per_instance=1;
    cp_iir_pending: coverpoint sampled_cp_iir_pending { bins pending_0={64'h0}; bins no_pending_1={64'h1}; }
    cp_iir_code: coverpoint sampled_cp_iir_code { bins code_000_modem={64'h0}; bins code_001_thre={64'h1}; bins code_010_rda={64'h2}; bins code_011_rls={64'h3}; bins code_110_timeout={64'h6}; bins illegal_100_101_111={64'h4, 64'h5, 64'h7}; }
    cp_iir_fixed_76: coverpoint sampled_cp_iir_fixed_76 { bins fixed_76_11={64'h3}; bins illegal_fixed_76_other={64'h0, 64'h1, 64'h2}; }
    cp_iir_fixed_54: coverpoint sampled_cp_iir_fixed_54 { bins fixed_54_00={64'h0}; bins illegal_fixed_54_other={64'h1, 64'h2, 64'h3}; }

  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if((observed.kind==1) && observed.address==64'h2) begin
      sampled_cp_iir_pending=(observed.data & 64'h1) >> 0;
      sampled_cp_iir_code=(observed.data & 64'he) >> 1;
      sampled_cp_iir_fixed_76=(observed.data & 64'hc0) >> 6;
      sampled_cp_iir_fixed_54=(observed.data & 64'h30) >> 4;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_irq_id_cov_cg_iir samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
