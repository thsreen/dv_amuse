// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_wb_init_cfg_cg_dlab_divisor_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_wb_init_cfg_cg_dlab_divisor_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_cp_dlab;
  longint unsigned sampled_cp_div_lsb;
  longint unsigned sampled_cp_div_msb;
  covergroup transactions;
    option.per_instance=1;
    cp_dlab: coverpoint sampled_cp_dlab { bins dlab_1_divisor={64'h0, 64'h1}; bins dlab_0_normal={64'h2, 64'h3}; }
    cp_div_lsb: coverpoint sampled_cp_div_lsb { bins lsb_zero_0x00={64'h0}; bins lsb_min_0x01={64'h1}; bins lsb_mid_low={64'h2, 64'h40, 64'h7f}; bins lsb_mid_high={64'h80, 64'hc0, 64'hfe}; bins lsb_max_0xFF={64'hff}; }
    cp_div_msb: coverpoint sampled_cp_div_msb { bins msb_zero_0x00={64'h0}; bins msb_min_0x01={64'h1}; bins msb_mid_low={64'h2, 64'h40, 64'h7f}; bins msb_mid_high={64'h80, 64'hc0, 64'hfe}; bins msb_max_0xFF={64'hff}; }

  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if(1) begin
      sampled_cp_dlab=(observed.address & 64'h7) >> 0;
      sampled_cp_div_lsb=(observed.data & 64'hff) >> 0;
      sampled_cp_div_msb=(observed.data & 64'hff) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_wb_init_cfg_cg_dlab_divisor samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
