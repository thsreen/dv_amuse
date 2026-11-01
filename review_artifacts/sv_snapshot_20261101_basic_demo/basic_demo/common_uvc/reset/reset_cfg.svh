// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
  class reset_cfg extends uvm_object;
    `uvm_object_utils(reset_cfg)
    virtual reset_if vif;
    uvm_active_passive_enum is_active = UVM_ACTIVE;
    bit polarity_set = 0;
    bit active_level;
    realtime assert_time = 100ns;
    bit auto_pulse = 1;

    function new(string name = "reset_cfg");
      super.new(name);
    endfunction

    function void validate();
      if (vif == null)
        `uvm_fatal("RESET_VIF", "reset_if virtual interface is missing")
      if (!polarity_set)
        `uvm_fatal("RESET_CFG", "reset active level must be explicitly configured")
      if (assert_time == 0)
        `uvm_fatal("RESET_CFG", "assert_time must be positive")
    endfunction
  endclass
