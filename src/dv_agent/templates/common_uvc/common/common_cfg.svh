  // Configuration of the common clock/reset environment. A project supplies only the bindings:
  // which virtual interfaces, the reset active level, the clock period and the reset duration.
  class common_cfg extends uvm_object;
    `uvm_object_utils(common_cfg)
    clock_cfg clock;
    reset_cfg reset;

    function new(string name = "common_cfg");
      super.new(name);
      clock = clock_cfg::type_id::create("clock");
      reset = reset_cfg::type_id::create("reset");
    endfunction

    function void bind_clock(virtual clock_if vif, realtime period);
      clock.vif = vif;
      clock.period = period;
    endfunction

    function void bind_reset(virtual reset_if vif, bit active_high, realtime assert_time, bit auto_pulse = 0);
      reset.vif = vif;
      reset.polarity_set = 1;
      reset.active_level = active_high;
      reset.assert_time = assert_time;
      reset.auto_pulse = auto_pulse;
    endfunction

    function void validate();
      clock.validate();
      reset.validate();
    endfunction
  endclass
