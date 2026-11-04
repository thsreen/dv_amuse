class wishbone_slave_interface_agent extends uvm_agent;
  `uvm_component_utils(wishbone_slave_interface_agent)
  wishbone_slave_interface_cfg cfg;
  wishbone_slave_interface_sequencer sqr;
  wishbone_slave_interface_driver drv;
  wishbone_slave_interface_monitor mon;

  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    mon = wishbone_slave_interface_monitor::type_id::create("mon", this); mon.cfg = cfg;

    if (cfg.active) begin
      sqr = wishbone_slave_interface_sequencer::type_id::create("sqr", this); sqr.cfg = cfg;
      drv = wishbone_slave_interface_driver::type_id::create("drv", this); drv.cfg = cfg;
    end
  endfunction
  function void connect_phase(uvm_phase phase);
    if (cfg.active) drv.seq_item_port.connect(sqr.seq_item_export);

  endfunction
endclass
