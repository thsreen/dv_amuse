// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class serial_link_agent extends uvm_agent;
  `uvm_component_utils(serial_link_agent)
  serial_link_cfg cfg;
  serial_link_sequencer sqr;
  serial_link_driver drv;
  serial_link_monitor mon;
  serial_link_coverage cov;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    mon = serial_link_monitor::type_id::create("mon", this); mon.cfg = cfg;
    cov=serial_link_coverage::type_id::create("cov",this); cov.cfg=cfg;
    if (cfg.active) begin
      sqr = serial_link_sequencer::type_id::create("sqr", this); sqr.cfg = cfg;
      drv = serial_link_driver::type_id::create("drv", this); drv.cfg = cfg;
    end
  endfunction
  function void connect_phase(uvm_phase phase);
    if (cfg.active) drv.seq_item_port.connect(sqr.seq_item_export);
    mon.ap.connect(cov.analysis_export);
  endfunction
endclass
