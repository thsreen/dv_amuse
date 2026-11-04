// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class uart_serial_data_agent extends uvm_agent;
  `uvm_component_utils(uart_serial_data_agent)
  uart_serial_data_cfg cfg;
  uart_serial_data_sequencer sqr;
  uart_serial_data_driver drv;
  uart_serial_data_monitor mon;

  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    mon = uart_serial_data_monitor::type_id::create("mon", this); mon.cfg = cfg;

    if (cfg.active) begin
      sqr = uart_serial_data_sequencer::type_id::create("sqr", this); sqr.cfg = cfg;
      drv = uart_serial_data_driver::type_id::create("drv", this); drv.cfg = cfg;
    end
  endfunction
  function void connect_phase(uvm_phase phase);
    if (cfg.active) drv.seq_item_port.connect(sqr.seq_item_export);

  endfunction
endclass
