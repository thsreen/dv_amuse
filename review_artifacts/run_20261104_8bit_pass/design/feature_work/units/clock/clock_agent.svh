
  class clock_agent extends uvm_agent;
    `uvm_component_utils(clock_agent)
    clock_cfg cfg;
    clock_driver drv;
    clock_monitor mon;
    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if (!uvm_config_db #(clock_cfg)::get(this, "", "cfg", cfg))
        `uvm_fatal("CLOCK_CFG", "clock agent configuration is missing")
      cfg.validate();
      mon = clock_monitor::type_id::create("mon", this);
      mon.cfg = cfg;
      if (cfg.is_active == UVM_ACTIVE) begin
        drv = clock_driver::type_id::create("drv", this);
        drv.cfg = cfg;
      end
    endfunction
  endclass
