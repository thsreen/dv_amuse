// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_modem_traffic_cov_cg_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(t_modem_traffic_cov_cg_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_t_modem_traffic_cov_cp_modem;
  longint unsigned sampled_t_modem_traffic_cov_cp_traffic;
  covergroup transactions;
    option.per_instance=1;
    t_modem_traffic_cov_cp_modem: coverpoint sampled_t_modem_traffic_cov_cp_modem { bins modem_000={64'hc0}; bins no_modem={64'hc1}; }
    t_modem_traffic_cov_cp_traffic: coverpoint sampled_t_modem_traffic_cov_cp_traffic { bins idle={64'h0}; bins tx_active={64'h1}; bins rx_active={64'h2}; bins tx_rx_active={64'h3}; bins traffic={64'h4}; }
    t_modem_traffic_cov_cross: cross t_modem_traffic_cov_cp_modem, t_modem_traffic_cov_cp_traffic;
  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if((observed.kind==1) && observed.address==64'h2) begin
      sampled_t_modem_traffic_cov_cp_modem=(observed.data & 64'hff) >> 0;
      sampled_t_modem_traffic_cov_cp_traffic=(observed.kind & 64'h7) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("t_modem_traffic_cov_cg samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
