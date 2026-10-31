class register_bus_agent extends uvm_agent;
  `uvm_component_utils(register_bus_agent)
  register_bus_cfg cfg;
  register_bus_sequencer sqr;
  register_bus_driver drv;
  register_bus_monitor mon;
  register_bus_coverage cov;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    mon = register_bus_monitor::type_id::create("mon", this); mon.cfg = cfg;
    cov=register_bus_coverage::type_id::create("cov",this); cov.cfg=cfg;
    if (cfg.active) begin
      sqr = register_bus_sequencer::type_id::create("sqr", this); sqr.cfg = cfg;
      drv = register_bus_driver::type_id::create("drv", this); drv.cfg = cfg;
    end
  endfunction
  function void connect_phase(uvm_phase phase);
    if (cfg.active) drv.seq_item_port.connect(sqr.seq_item_export);
    mon.ap.connect(cov.analysis_export);
  endfunction
endclass
