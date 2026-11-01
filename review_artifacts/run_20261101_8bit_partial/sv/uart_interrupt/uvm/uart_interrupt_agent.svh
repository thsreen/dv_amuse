class uart_interrupt_agent extends uvm_agent;
  `uvm_component_utils(uart_interrupt_agent)
  uart_interrupt_cfg cfg;
  uart_interrupt_monitor mon;

  function new(string name, uvm_component parent); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    mon=uart_interrupt_monitor::type_id::create("mon",this); mon.cfg=cfg;

  endfunction
  function void connect_phase(uvm_phase phase);

  endfunction
endclass
