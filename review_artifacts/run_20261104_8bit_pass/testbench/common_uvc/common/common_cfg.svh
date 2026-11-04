// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
  // Configuration of the common clock/reset environment. A project supplies only the bindings:
  // which virtual interfaces, the reset active level, clock period and reset duration.
  class common_cfg extends uvm_object;
    `uvm_object_utils(common_cfg)
    clock_cfg clk_cfg;
    reset_cfg rst_cfg;

    function new(string name = "common_cfg");
      super.new(name);
      clk_cfg = clock_cfg::type_id::create("clk_cfg");
      rst_cfg = reset_cfg::type_id::create("rst_cfg");
    endfunction

    function void bind_clock(virtual clock_if vif, realtime period);
      clk_cfg.vif = vif;
      clk_cfg.period = period;
    endfunction

    function void bind_reset(virtual reset_if vif, bit active_high, realtime assert_time, bit auto_pulse = 0);
      rst_cfg.vif = vif;
      rst_cfg.polarity_set = 1;
      rst_cfg.active_level = active_high;
      rst_cfg.assert_time = assert_time;
      rst_cfg.auto_pulse = auto_pulse;
    endfunction

    function void validate();
      clk_cfg.validate();
      rst_cfg.validate();
    endfunction
  endclass
