  // One agent for the testbench-supplied infrastructure: it instantiates the clock and reset UVCs and
  // hands each its own configuration. Custom UVCs can be added here later without touching a test.
  class common_agent extends uvm_agent;
    `uvm_component_utils(common_agent)
    common_cfg cfg;
    clock_agent clock_uvc;
    reset_agent reset_uvc;

    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if (!uvm_config_db #(common_cfg)::get(this, "", "cfg", cfg))
        `uvm_fatal("COMMON_CFG", "common agent configuration is missing")
      cfg.validate();
      uvm_config_db #(clock_cfg)::set(this, "clock_uvc", "cfg", cfg.clock);
      uvm_config_db #(reset_cfg)::set(this, "reset_uvc", "cfg", cfg.reset);
      clock_uvc = clock_agent::type_id::create("clock_uvc", this);
      reset_uvc = reset_agent::type_id::create("reset_uvc", this);
    endfunction

    // Apply one reset pulse using the reset UVC's own sequence.
    task apply_reset();
      reset_pulse_seq seq = reset_pulse_seq::type_id::create("seq");
      seq.cfg = cfg.reset;
      seq.start(reset_uvc.sqr);
    endtask
  endclass
