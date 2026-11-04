class interrupt_output_agent extends uvm_agent;
  `uvm_component_utils(interrupt_output_agent)
  interrupt_output_cfg cfg;
  interrupt_output_monitor mon;

  function new(string name, uvm_component parent); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    mon=interrupt_output_monitor::type_id::create("mon",this); mon.cfg=cfg;

  endfunction
  function void connect_phase(uvm_phase phase);

  endfunction
endclass
