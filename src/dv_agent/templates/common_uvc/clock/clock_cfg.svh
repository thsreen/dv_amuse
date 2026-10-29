  class clock_cfg extends uvm_object;
    `uvm_object_utils(clock_cfg)
    virtual clock_if vif;
    uvm_active_passive_enum is_active = UVM_ACTIVE;
    time period = 10ns;
    int unsigned duty_cycle_pct = 50;
    bit enabled = 1;
    bit idle_level = 0;

    function new(string name = "clock_cfg");
      super.new(name);
    endfunction

    function void validate();
      time high_time;
      time low_time;
      if (vif == null)
        `uvm_fatal("CLOCK_VIF", "clock_if virtual interface is missing")
      if (period == 0 || duty_cycle_pct == 0 || duty_cycle_pct >= 100)
        `uvm_fatal("CLOCK_CFG", "period and duty cycle must be positive; duty must be below 100")
      high_time = (period * duty_cycle_pct) / 100;
      low_time = period - high_time;
      if (high_time == 0 || low_time == 0)
        `uvm_fatal("CLOCK_CFG", "high and low intervals must each be at least one timeprecision step")
    endfunction
  endclass
