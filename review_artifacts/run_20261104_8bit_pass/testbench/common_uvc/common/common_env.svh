// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
  // Environment holding the common agent. A testbench instantiates this once and binds clock and reset.
  class common_env extends uvm_env;
    `uvm_component_utils(common_env)
    common_cfg cmn_cfg;
    common_agent cmn_agent;

    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if (!uvm_config_db #(common_cfg)::get(this, "", "cfg", cmn_cfg))
        `uvm_fatal("COMMON_CFG", "common environment configuration is missing")
      uvm_config_db #(common_cfg)::set(this, "cmn_agent", "cfg", cmn_cfg);
      cmn_agent = common_agent::type_id::create("cmn_agent", this);
    endfunction
  endclass
