class interrupt_output_monitor extends uvm_component;
  `uvm_component_utils(interrupt_output_monitor)
  interrupt_output_cfg cfg;
  uvm_analysis_port #(cg_item) ap;
  logic [0:0] sampled_INT_O;
  function new(string name, uvm_component parent); super.new(name,parent); ap=new("ap",this); endfunction
  virtual function void reset_values();
    sampled_INT_O = '0;
  endfunction
  virtual function void sample_signals();
    sampled_INT_O = cfg.vif.INT_O;
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
