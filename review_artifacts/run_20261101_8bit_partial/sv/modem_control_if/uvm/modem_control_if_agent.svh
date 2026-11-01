class modem_control_if_agent extends uvm_agent;
  `uvm_component_utils(modem_control_if_agent)
  modem_control_if_cfg cfg;
  modem_control_if_sequencer sqr;
  modem_control_if_driver drv;
  modem_control_if_monitor mon;

  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    mon = modem_control_if_monitor::type_id::create("mon", this); mon.cfg = cfg;

    if (cfg.active) begin
      sqr = modem_control_if_sequencer::type_id::create("sqr", this); sqr.cfg = cfg;
      drv = modem_control_if_driver::type_id::create("drv", this); drv.cfg = cfg;
    end
  endfunction
  function void connect_phase(uvm_phase phase);
    if (cfg.active) drv.seq_item_port.connect(sqr.seq_item_export);

  endfunction
endclass
