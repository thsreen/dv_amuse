// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.

  class clock_driver extends uvm_component;
    `uvm_component_utils(clock_driver)
    clock_cfg cfg;
    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    virtual task drive_clock();
      realtime high_time;
      realtime low_time;
      cfg.validate();
      cfg.vif.clk = cfg.idle_level;
      forever begin
        cfg.validate();
        if (!cfg.enabled) begin
          cfg.vif.clk = cfg.idle_level;
          #(cfg.period);
        end else begin
          high_time = $floor((cfg.period / 1ps) * cfg.duty_cycle_pct / 100.0) * 1ps;
          low_time = cfg.period - high_time;
          cfg.vif.clk = 1'b1;
          #(high_time);
          cfg.vif.clk = 1'b0;
          #(low_time);
        end
      end
    endtask

    task run_phase(uvm_phase phase);
      drive_clock();
    endtask
  endclass
