// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
  // One agent for the testbench-supplied infrastructure: it instantiates the clock and reset UVCs and
  // hands each its own configuration. Custom UVCs can be added here later without touching a test.
  class common_agent extends uvm_agent;
    `uvm_component_utils(common_agent)
    common_cfg cmn_cfg;
    clock_agent clk_agent;
    reset_agent rst_agent;

    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if (!uvm_config_db #(common_cfg)::get(this, "", "cfg", cmn_cfg))
        `uvm_fatal("COMMON_CFG", "common agent configuration is missing")
      cmn_cfg.validate();
      uvm_config_db #(clock_cfg)::set(this, "clk_agent", "cfg", cmn_cfg.clk_cfg);
      uvm_config_db #(reset_cfg)::set(this, "rst_agent", "cfg", cmn_cfg.rst_cfg);
      clk_agent = clock_agent::type_id::create("clk_agent", this);
      rst_agent = reset_agent::type_id::create("rst_agent", this);
    endfunction

    // Apply one reset pulse using the reset UVC's own sequence.
    task apply_reset();
      reset_pulse_seq seq = reset_pulse_seq::type_id::create("seq");
      seq.cfg = cmn_cfg.rst_cfg;
      seq.start(rst_agent.sqr);
    endtask
  endclass
