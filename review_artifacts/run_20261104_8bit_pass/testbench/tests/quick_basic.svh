// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class quick_basic extends uvm_test;
  `uvm_component_utils(quick_basic)
  cg_env cmn_env;
  common_cfg cmn_cfg;
  clock_cfg clk_cfg;
  reset_cfg rst_cfg;
  longint unsigned cg_clock_period_ps;
  interrupt_output_cfg interrupt_output_control;
  uart_serial_data_cfg uart_serial_data_control;
  modem_control_if_cfg modem_control_if_control;
  wishbone_slave_interface_cfg wishbone_slave_interface_control;
  function new(string name, uvm_component parent); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // Clock and reset come from the common environment; only their bindings are project specific.
    cmn_cfg=common_cfg::type_id::create("cmn_cfg");
    clk_cfg=cmn_cfg.clk_cfg; rst_cfg=cmn_cfg.rst_cfg;
    if(!uvm_config_db #(virtual clock_if)::get(this,"","clock_vif",clk_cfg.vif)) `uvm_fatal("CLOCK", "clock_vif missing")
    clk_cfg.period=10.0ns;

    if(!uvm_config_db #(virtual reset_if)::get(this,"","reset_vif",rst_cfg.vif)) `uvm_fatal("RESET", "reset_vif missing")
    cmn_cfg.bind_reset(rst_cfg.vif,1,clk_cfg.period * 10,0);
    uvm_config_db #(common_cfg)::set(this,"cmn_env","cfg",cmn_cfg);
    cmn_env=cg_env::type_id::create("cmn_env",this);
    interrupt_output_control=interrupt_output_cfg::type_id::create("interrupt_output_control");
    if(!uvm_config_db #(virtual interrupt_output_if)::get(this,"","interrupt_output_vif",interrupt_output_control.vif)) `uvm_fatal("VIF", "interrupt_output_vif missing")
    cmn_env.interrupt_output_control=interrupt_output_control;
    uart_serial_data_control=uart_serial_data_cfg::type_id::create("uart_serial_data_control");
    if(!uvm_config_db #(virtual uart_serial_data_if)::get(this,"","uart_serial_data_vif",uart_serial_data_control.vif)) `uvm_fatal("VIF", "uart_serial_data_vif missing")
    cmn_env.uart_serial_data_control=uart_serial_data_control;
    modem_control_if_control=modem_control_if_cfg::type_id::create("modem_control_if_control");
    if(!uvm_config_db #(virtual modem_control_if_if)::get(this,"","modem_control_if_vif",modem_control_if_control.vif)) `uvm_fatal("VIF", "modem_control_if_vif missing")
    cmn_env.modem_control_if_control=modem_control_if_control;
    wishbone_slave_interface_control=wishbone_slave_interface_cfg::type_id::create("wishbone_slave_interface_control");
    if(!uvm_config_db #(virtual wishbone_slave_interface_if)::get(this,"","wishbone_slave_interface_vif",wishbone_slave_interface_control.vif)) `uvm_fatal("VIF", "wishbone_slave_interface_vif missing")
    cmn_env.wishbone_slave_interface_control=wishbone_slave_interface_control;
  endfunction
  function void connect_phase(uvm_phase phase);

    cmn_env.sb.reset_vif=rst_cfg.vif; cmn_env.sb.reset_active=1;
    cmn_env.sb.minimum_comparisons=2;
    cmn_env.system_cov.reset_vif=rst_cfg.vif; cmn_env.system_cov.reset_active=1; cmn_env.system_cov.flush();
  endfunction
  task run_phase(uvm_phase phase);
    quick_basic_vseq seq;
    phase.raise_objection(this);
    cmn_env.cmn_agent.apply_reset();
    seq=quick_basic_vseq::type_id::create("seq");
    cg_reg_map::get_map().bind_sequencer("wishbone_slave_interface",cmn_env.wishbone_slave_interface.sqr);
    seq.uart_serial_data_sqr=cmn_env.uart_serial_data.sqr;
    seq.modem_control_if_sqr=cmn_env.modem_control_if.sqr;
    seq.wishbone_slave_interface_sqr=cmn_env.wishbone_slave_interface.sqr;
    seq.start(null);
    phase.drop_objection(this);
  endtask
  function void report_phase(uvm_phase phase);
    uvm_report_server server;
    server=uvm_report_server::get_server();
    if(server.get_severity_count(UVM_ERROR)==0 && server.get_severity_count(UVM_FATAL)==0)
      $display("FUNCTIONAL_TEST_PASS quick_basic");
  endfunction
endclass
