class basic_functional extends uvm_test;
  `uvm_component_utils(basic_functional)
  cg_env cmn_env;
  common_cfg cmn_cfg;
  clock_cfg clk_cfg;
  reset_cfg rst_cfg;
  longint unsigned cg_clock_period_ps;
  register_bus_cfg register_bus_control;
  serial_link_cfg serial_link_control;
  function new(string name, uvm_component parent); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // Clock and reset come from the common environment; only their bindings are project specific.
    cmn_cfg=common_cfg::type_id::create("cmn_cfg");
    clk_cfg=cmn_cfg.clk_cfg; rst_cfg=cmn_cfg.rst_cfg;
    if(!uvm_config_db #(virtual clock_if)::get(this,"","clock_vif",clk_cfg.vif)) `uvm_fatal("CLOCK", "clock_vif missing")
    clk_cfg.period=10ns;

    if(!uvm_config_db #(virtual reset_if)::get(this,"","reset_vif",rst_cfg.vif)) `uvm_fatal("RESET", "reset_vif missing")
    cmn_cfg.bind_reset(rst_cfg.vif,1,clk_cfg.period * 8,0);
    uvm_config_db #(common_cfg)::set(this,"cmn_env","cfg",cmn_cfg);
    cmn_env=cg_env::type_id::create("cmn_env",this);
    register_bus_control=register_bus_cfg::type_id::create("register_bus_control");
    if(!uvm_config_db #(virtual register_bus_if)::get(this,"","register_bus_vif",register_bus_control.vif)) `uvm_fatal("VIF", "register_bus_vif missing")
    cmn_env.register_bus_control=register_bus_control;
    serial_link_control=serial_link_cfg::type_id::create("serial_link_control");
    if(!uvm_config_db #(virtual serial_link_if)::get(this,"","serial_link_vif",serial_link_control.vif)) `uvm_fatal("VIF", "serial_link_vif missing")
    cmn_env.serial_link_control=serial_link_control;
  endfunction
  function void connect_phase(uvm_phase phase);

    cmn_env.sb.reset_vif=rst_cfg.vif; cmn_env.sb.reset_active=1;
    cmn_env.sb.minimum_comparisons=3;
    cmn_env.system_cov.reset_vif=rst_cfg.vif; cmn_env.system_cov.reset_active=1; cmn_env.system_cov.flush();
  endfunction
  task run_phase(uvm_phase phase);
    basic_functional_vseq seq;
    phase.raise_objection(this);
    cmn_env.cmn_agent.apply_reset();
    seq=basic_functional_vseq::type_id::create("seq");
    seq.register_bus_sqr=cmn_env.register_bus.sqr;
    seq.serial_link_sqr=cmn_env.serial_link.sqr;
    seq.start(null);
    phase.drop_objection(this);
  endtask
  function void report_phase(uvm_phase phase);
    uvm_report_server server;
    server=uvm_report_server::get_server();
    if(server.get_severity_count(UVM_ERROR)==0 && server.get_severity_count(UVM_FATAL)==0)
      $display("FUNCTIONAL_TEST_PASS basic_functional");
  endfunction
endclass
