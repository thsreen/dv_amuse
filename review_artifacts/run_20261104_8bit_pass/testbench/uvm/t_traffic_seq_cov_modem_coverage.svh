// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_traffic_seq_cov_modem_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_traffic_seq_cov_modem_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_t_traffic_seq_cov_modem_pins;
  longint unsigned sampled_t_traffic_seq_cov_modem_lb;
  covergroup transactions;
    option.per_instance=1;
    t_traffic_seq_cov_modem_pins: coverpoint sampled_t_traffic_seq_cov_modem_pins { bins all_low={64'h0}; bins all_high={64'h3f}; bins mid={64'h15, 64'h2a}; }
    t_traffic_seq_cov_modem_lb: coverpoint sampled_t_traffic_seq_cov_modem_lb { bins normal={64'h0}; bins loopback={64'h1}; }
    t_traffic_seq_cov_modem_x: cross t_traffic_seq_cov_modem_pins, t_traffic_seq_cov_modem_lb;
  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if(1) begin
      sampled_t_traffic_seq_cov_modem_pins=(observed.data & 64'h3f) >> 0;
      sampled_t_traffic_seq_cov_modem_lb=(observed.data & 64'h10) >> 4;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_traffic_seq_cov_modem samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
