class wishbone_bus_agent extends uvm_agent;
  `uvm_component_utils(wishbone_bus_agent)
  wishbone_bus_cfg cfg;
  wishbone_bus_sequencer sqr;
  wishbone_bus_driver drv;
  wishbone_bus_monitor mon;

  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    mon = wishbone_bus_monitor::type_id::create("mon", this); mon.cfg = cfg;

    if (cfg.active) begin
      sqr = wishbone_bus_sequencer::type_id::create("sqr", this); sqr.cfg = cfg;
      drv = wishbone_bus_driver::type_id::create("drv", this); drv.cfg = cfg;
    end
  endfunction
  function void connect_phase(uvm_phase phase);
    if (cfg.active) drv.seq_item_port.connect(sqr.seq_item_export);

  endfunction
endclass
