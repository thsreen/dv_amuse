
  class clock_driver extends uvm_component;
    `uvm_component_utils(clock_driver)
    clock_cfg cfg;
    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    virtual task drive_clock();
      time high_time;
      time low_time;
      cfg.validate();
      cfg.vif.clk = cfg.idle_level;
      forever begin
        cfg.validate();
        if (!cfg.enabled) begin
          cfg.vif.clk = cfg.idle_level;
          #(cfg.period);
        end else begin
          high_time = (cfg.period * cfg.duty_cycle_pct) / 100;
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
