// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class modem_control_if_monitor extends uvm_component;
  `uvm_component_utils(modem_control_if_monitor)
  modem_control_if_cfg cfg;
  uvm_analysis_port #(cg_item) ap;
  logic [0:0] sampled_RTS_PAD_O;
  logic [0:0] sampled_DTR_PAD_O;
  logic [0:0] sampled_CTS_PAD_I;
  logic [0:0] sampled_DSR_PAD_I;
  logic [0:0] sampled_RI_PAD_I;
  logic [0:0] sampled_DCD_PAD_I;
  function new(string name, uvm_component parent); super.new(name,parent); ap=new("ap",this); endfunction
  virtual function void reset_values();
    sampled_RTS_PAD_O = '0;
    sampled_DTR_PAD_O = '0;
    sampled_CTS_PAD_I = '0;
    sampled_DSR_PAD_I = '0;
    sampled_RI_PAD_I = '0;
    sampled_DCD_PAD_I = '0;
  endfunction
  virtual function void sample_signals();
    sampled_RTS_PAD_O = cfg.vif.RTS_PAD_O;
    sampled_DTR_PAD_O = cfg.vif.DTR_PAD_O;
    sampled_CTS_PAD_I = cfg.vif.CTS_PAD_I;
    sampled_DSR_PAD_I = cfg.vif.DSR_PAD_I;
    sampled_RI_PAD_I = cfg.vif.RI_PAD_I;
    sampled_DCD_PAD_I = cfg.vif.DCD_PAD_I;
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
