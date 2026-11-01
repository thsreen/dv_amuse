
  class reset_agent extends uvm_agent;
    `uvm_component_utils(reset_agent)
    reset_cfg cfg;
    reset_sequencer sqr;
    reset_driver drv;
    reset_monitor mon;
    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if (!uvm_config_db #(reset_cfg)::get(this, "", "cfg", cfg))
        `uvm_fatal("RESET_CFG", "reset agent configuration is missing")
      cfg.validate();
      mon = reset_monitor::type_id::create("mon", this);
      mon.cfg = cfg;
      if (cfg.is_active == UVM_ACTIVE) begin
        sqr = reset_sequencer::type_id::create("sqr", this);
        sqr.cfg = cfg;
        drv = reset_driver::type_id::create("drv", this);
        drv.cfg = cfg;
      end
    endfunction

    function void connect_phase(uvm_phase phase);
      if (cfg.is_active == UVM_ACTIVE)
        drv.seq_item_port.connect(sqr.seq_item_export);
    endfunction
  endclass
