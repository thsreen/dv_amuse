// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_wb_init_cfg_rc_divisor_bytes_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_wb_init_cfg_rc_divisor_bytes_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_cp_lsb_val;
  longint unsigned sampled_cp_msb_val;
  covergroup transactions;
    option.per_instance=1;
    cp_lsb_val: coverpoint sampled_cp_lsb_val { bins lsb_zero_0x00={64'h0}; bins lsb_mid_0x01_0xFE={64'h1, 64'h7f, 64'hfe}; bins lsb_max_0xFF={64'hff}; }
    cp_msb_val: coverpoint sampled_cp_msb_val { bins msb_zero_0x00={64'h0}; bins msb_mid_0x01_0xFE={64'h1, 64'h7f, 64'hfe}; bins msb_max_0xFF={64'hff}; }
    rc_combined: cross cp_lsb_val, cp_msb_val;
  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if(1) begin
      sampled_cp_lsb_val=(observed.data & 64'hff) >> 0;
      sampled_cp_msb_val=(observed.data & 64'hff) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_wb_init_cfg_rc_divisor_bytes samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
