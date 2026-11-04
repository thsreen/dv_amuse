// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class cg_system_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(cg_system_coverage)
  cg_item observed;
  int route_event;
  int unsigned samples;
  virtual reset_if reset_vif;
  bit reset_active;
  longint unsigned qualification_quick_basic_transmit_0;
  bit qualification_quick_basic_transmit_0_valid;
  longint unsigned qualification_quick_basic_receive_0;
  bit qualification_quick_basic_receive_0_valid;
  covergroup interactions;
    option.per_instance=1;
    cp_route_activity: coverpoint route_event { bins quick_basic_transmit_expected={0};
bins quick_basic_transmit_actual={1};
bins quick_basic_receive_expected={2};
bins quick_basic_receive_actual={3}; }
  endgroup
  function new(string name, uvm_component parent); super.new(name,parent); interactions=new(); endfunction
  function void flush();
    qualification_quick_basic_transmit_0=64'h3; qualification_quick_basic_transmit_0_valid=1;
    qualification_quick_basic_receive_0=64'h3; qualification_quick_basic_receive_0_valid=1;
  endfunction
  task run_phase(uvm_phase phase);
    forever begin @(reset_vif.reset); if(reset_vif.reset==reset_active) flush(); end
  endtask
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("SYSTEM_COV_COPY", "transaction copy failed")
    if(observed.origin=="wishbone_slave_interface" && observed.kind==1 && observed.address==64'h3) begin qualification_quick_basic_transmit_0=observed.data; qualification_quick_basic_transmit_0_valid=1; end
    if(observed.origin=="wishbone_slave_interface" && observed.kind==1 && observed.address==64'h3) begin qualification_quick_basic_receive_0=observed.data; qualification_quick_basic_receive_0_valid=1; end
    if(observed.origin=="wishbone_slave_interface" && observed.kind==1 && observed.address==64'h0 && (qualification_quick_basic_transmit_0_valid && (qualification_quick_basic_transmit_0 & 64'h80)==64'h0)) begin route_event=0; samples++; interactions.sample(); end
    if(observed.origin=="uart_serial_data" && observed.kind==4 && (qualification_quick_basic_transmit_0_valid && (qualification_quick_basic_transmit_0 & 64'h80)==64'h0)) begin route_event=1; samples++; interactions.sample(); end
    if(observed.origin=="uart_serial_data" && observed.kind==3 && (qualification_quick_basic_receive_0_valid && (qualification_quick_basic_receive_0 & 64'h80)==64'h0)) begin route_event=2; samples++; interactions.sample(); end
    if(observed.origin=="wishbone_slave_interface" && observed.kind==2 && observed.address==64'h0 && (qualification_quick_basic_receive_0_valid && (qualification_quick_basic_receive_0 & 64'h80)==64'h0)) begin route_event=3; samples++; interactions.sample(); end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("SYSTEM_COVERAGE", $sformatf("samples=%0d coverage=%0.2f", samples,interactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
