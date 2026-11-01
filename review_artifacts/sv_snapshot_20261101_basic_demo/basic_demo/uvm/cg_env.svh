// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class cg_env extends common_env;
  `uvm_component_utils(cg_env)
  cg_scoreboard sb;
  cg_system_coverage system_cov;
  register_bus_agent register_bus;
  register_bus_cfg register_bus_control;
  serial_link_agent serial_link;
  serial_link_cfg serial_link_control;
  function new(string name, uvm_component parent); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    sb=cg_scoreboard::type_id::create("sb",this);
    system_cov=cg_system_coverage::type_id::create("system_cov",this);
    register_bus=register_bus_agent::type_id::create("register_bus",this); register_bus.cfg=register_bus_control;
    serial_link=serial_link_agent::type_id::create("serial_link",this); serial_link.cfg=serial_link_control;
    sb.flush();
  endfunction
  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    register_bus.mon.ap.connect(sb.analysis_export);
    register_bus.mon.ap.connect(system_cov.analysis_export);
    serial_link.mon.ap.connect(sb.analysis_export);
    serial_link.mon.ap.connect(system_cov.analysis_export);
  endfunction
endclass
