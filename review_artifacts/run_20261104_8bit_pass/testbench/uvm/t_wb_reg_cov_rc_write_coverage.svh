// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_wb_reg_cov_rc_write_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_wb_reg_cov_rc_write_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_cp_reg_write_addr;
  covergroup transactions;
    option.per_instance=1;
    cp_reg_write_addr: coverpoint sampled_cp_reg_write_addr { bins reg0_W_THR={64'h0}; bins reg1_W_IER={64'h1}; bins reg2_W_FCR={64'h2}; bins reg3_W_LCR={64'h3}; bins reg4_W_MCR={64'h4}; bins illegal_addr_7={64'h7}; }

  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if((observed.kind==1)) begin
      sampled_cp_reg_write_addr=(observed.address & 64'h7) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_wb_reg_cov_rc_write samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
