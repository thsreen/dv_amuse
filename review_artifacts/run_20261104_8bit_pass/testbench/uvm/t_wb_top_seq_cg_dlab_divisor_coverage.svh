// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_wb_top_seq_cg_dlab_divisor_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_wb_top_seq_cg_dlab_divisor_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_t_wb_top_seq_d_p_dlab;
  longint unsigned sampled_t_wb_top_seq_d_p_addr;
  longint unsigned sampled_t_wb_top_seq_d_p_data;
  covergroup transactions;
    option.per_instance=1;
    t_wb_top_seq_d_p_dlab: coverpoint sampled_t_wb_top_seq_d_p_dlab { bins b_dlab0={64'h0}; bins b_dlab1={64'h1}; }
    t_wb_top_seq_d_p_addr: coverpoint sampled_t_wb_top_seq_d_p_addr { bins b_addr0={64'h0}; bins b_addr1={64'h1}; }
    t_wb_top_seq_d_p_data: coverpoint sampled_t_wb_top_seq_d_p_data { bins b_zero={64'h0}; bins b_min={64'h1}; bins b_mid_low={64'h40}; bins b_mid_high={64'hc0}; bins b_max={64'hff}; }
    cr_div_dlab_addr_data: cross t_wb_top_seq_d_p_dlab, t_wb_top_seq_d_p_addr, t_wb_top_seq_d_p_data;
  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if((observed.kind==1)) begin
      sampled_t_wb_top_seq_d_p_dlab=(observed.data & 64'h80) >> 7;
      sampled_t_wb_top_seq_d_p_addr=(observed.address & 64'h7) >> 0;
      sampled_t_wb_top_seq_d_p_data=(observed.data & 64'hff) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_wb_top_seq_cg_dlab_divisor samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
