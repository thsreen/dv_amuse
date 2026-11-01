class modem_control_if_monitor extends uvm_component;
  `uvm_component_utils(modem_control_if_monitor)
  modem_control_if_cfg cfg;
  uvm_analysis_port #(cg_item) ap;
  logic [0:0] sampled_rts_pad_o;
  logic [0:0] sampled_dtr_pad_o;
  logic [0:0] sampled_cts_pad_i;
  logic [0:0] sampled_dsr_pad_i;
  logic [0:0] sampled_ri_pad_i;
  logic [0:0] sampled_dcd_pad_i;
  function new(string name, uvm_component parent); super.new(name,parent); ap=new("ap",this); endfunction
  virtual function void reset_values();
    sampled_rts_pad_o = '0;
    sampled_dtr_pad_o = '0;
    sampled_cts_pad_i = '0;
    sampled_dsr_pad_i = '0;
    sampled_ri_pad_i = '0;
    sampled_dcd_pad_i = '0;
  endfunction
  virtual function void sample_signals();
    sampled_rts_pad_o = cfg.vif.rts_pad_o;
    sampled_dtr_pad_o = cfg.vif.dtr_pad_o;
    sampled_cts_pad_i = cfg.vif.cts_pad_i;
    sampled_dsr_pad_i = cfg.vif.dsr_pad_i;
    sampled_ri_pad_i = cfg.vif.ri_pad_i;
    sampled_dcd_pad_i = cfg.vif.dcd_pad_i;
  endfunction
  virtual task monitor_interface();
    // No protocol observation is declared for this agent.
  endtask
  task run_phase(uvm_phase phase);
    reset_values();
    fork
      forever begin
        @(posedge cfg.vif.clk);
        if (cfg.vif.reset == cfg.reset_active) reset_values();
        else sample_signals();
      end
      monitor_interface();
    join
  endtask
endclass
