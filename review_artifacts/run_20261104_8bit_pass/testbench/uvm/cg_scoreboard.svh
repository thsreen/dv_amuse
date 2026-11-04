// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class cg_scoreboard extends uvm_subscriber #(cg_item);
  `uvm_component_utils(cg_scoreboard)
  virtual reset_if reset_vif;
  bit reset_active;
  int unsigned comparisons;
  int unsigned minimum_comparisons=1;
  longint unsigned qualification_quick_basic_transmit_0;
  bit qualification_quick_basic_transmit_0_valid;
  longint unsigned qualification_quick_basic_receive_0;
  bit qualification_quick_basic_receive_0_valid;
  longint unsigned mirror_t_wb_init_cfg_lcr;
  bit valid_t_wb_init_cfg_lcr;
  longint unsigned mirror_t_wb_init_cfg_fcr;
  bit valid_t_wb_init_cfg_fcr;
  longint unsigned mirror_t_divisor_cov_msb;
  bit valid_t_divisor_cov_msb;
  longint unsigned mirror_t_traffic_seq_mcr;
  bit valid_t_traffic_seq_mcr;
  longint unsigned expected_quick_basic_transmit[$], actual_quick_basic_transmit[$];
  longint unsigned expected_quick_basic_receive[$], actual_quick_basic_receive[$];
  function new(string name, uvm_component parent); super.new(name,parent); endfunction
  function void flush();
    qualification_quick_basic_transmit_0=64'h3; qualification_quick_basic_transmit_0_valid=1;
    qualification_quick_basic_receive_0=64'h3; qualification_quick_basic_receive_0_valid=1;
    mirror_t_wb_init_cfg_lcr=64'h0; valid_t_wb_init_cfg_lcr=0;
    mirror_t_wb_init_cfg_fcr=64'h0; valid_t_wb_init_cfg_fcr=0;
    mirror_t_divisor_cov_msb=64'h0; valid_t_divisor_cov_msb=0;
    mirror_t_traffic_seq_mcr=64'h0; valid_t_traffic_seq_mcr=1;
    expected_quick_basic_transmit.delete(); actual_quick_basic_transmit.delete();
    expected_quick_basic_receive.delete(); actual_quick_basic_receive.delete();
  endfunction
  task run_phase(uvm_phase phase);
    forever begin
      @(reset_vif.reset);
      if(reset_vif.reset == reset_active) flush();
    end
  endtask
  function void write(cg_item item);
    cg_item tr;
    if (!$cast(tr, item.clone())) `uvm_fatal("SB_COPY", "transaction copy failed")
    if (tr.error) `uvm_error("FRAME_ERROR", "observed malformed frame")
    if(tr.origin=="wishbone_slave_interface" && tr.address==64'h3) begin
      if(tr.kind==1) begin mirror_t_wb_init_cfg_lcr=(mirror_t_wb_init_cfg_lcr & ~64'hff) | (tr.data & 64'hff); valid_t_wb_init_cfg_lcr=1; end
      if(tr.kind==2 && valid_t_wb_init_cfg_lcr) begin comparisons++;
        if((tr.data & 64'hff) != (mirror_t_wb_init_cfg_lcr & 64'hff)) `uvm_error("REGISTER_MISMATCH", "t_wb_init_cfg_lcr")
      end
    end
    if(tr.origin=="wishbone_slave_interface" && tr.address==64'h2) begin
      if(tr.kind==1) begin mirror_t_wb_init_cfg_fcr=(mirror_t_wb_init_cfg_fcr & ~64'hff) | (tr.data & 64'hff); valid_t_wb_init_cfg_fcr=1; end
    end
    if(tr.origin=="wishbone_slave_interface" && tr.address==64'h1) begin
      if(tr.kind==1) begin mirror_t_divisor_cov_msb=(mirror_t_divisor_cov_msb & ~64'hff) | (tr.data & 64'hff); valid_t_divisor_cov_msb=1; end
      if(tr.kind==2 && valid_t_divisor_cov_msb) begin comparisons++;
        if((tr.data & 64'hff) != (mirror_t_divisor_cov_msb & 64'hff)) `uvm_error("REGISTER_MISMATCH", "t_divisor_cov_msb")
      end
    end
    if(tr.origin=="wishbone_slave_interface" && tr.address==64'h4) begin
      if(tr.kind==1) begin mirror_t_traffic_seq_mcr=(mirror_t_traffic_seq_mcr & ~64'h1f) | (tr.data & 64'h1f); valid_t_traffic_seq_mcr=1; end
    end
    if(tr.origin=="wishbone_slave_interface" && tr.kind==1 && tr.address==64'h3) begin qualification_quick_basic_transmit_0=tr.data; qualification_quick_basic_transmit_0_valid=1; end
    if(tr.origin=="wishbone_slave_interface" && tr.kind==1 && tr.address==64'h3) begin qualification_quick_basic_receive_0=tr.data; qualification_quick_basic_receive_0_valid=1; end
    if(tr.origin=="wishbone_slave_interface" && tr.kind==1 && tr.address==64'h0 && (qualification_quick_basic_transmit_0_valid && (qualification_quick_basic_transmit_0 & 64'h80)==64'h0)) expected_quick_basic_transmit.push_back(tr.data & 64'hff);
    if(tr.origin=="uart_serial_data" && tr.kind==4 && (qualification_quick_basic_transmit_0_valid && (qualification_quick_basic_transmit_0 & 64'h80)==64'h0)) actual_quick_basic_transmit.push_back(tr.data & 64'hff);
    while(expected_quick_basic_transmit.size()!=0 && actual_quick_basic_transmit.size()!=0) begin
      longint unsigned e, a; e=expected_quick_basic_transmit.pop_front(); a=actual_quick_basic_transmit.pop_front(); comparisons++;
      if(e != a) `uvm_error("DATA_MISMATCH", $sformatf("quick_basic_transmit: expected=%h actual=%h", e,a))
    end
    if(tr.origin=="uart_serial_data" && tr.kind==3 && (qualification_quick_basic_receive_0_valid && (qualification_quick_basic_receive_0 & 64'h80)==64'h0)) expected_quick_basic_receive.push_back(tr.data & 64'hff);
    if(tr.origin=="wishbone_slave_interface" && tr.kind==2 && tr.address==64'h0 && (qualification_quick_basic_receive_0_valid && (qualification_quick_basic_receive_0 & 64'h80)==64'h0)) actual_quick_basic_receive.push_back(tr.data & 64'hff);
    while(expected_quick_basic_receive.size()!=0 && actual_quick_basic_receive.size()!=0) begin
      longint unsigned e, a; e=expected_quick_basic_receive.pop_front(); a=actual_quick_basic_receive.pop_front(); comparisons++;
      if(e != a) `uvm_error("DATA_MISMATCH", $sformatf("quick_basic_receive: expected=%h actual=%h", e,a))
    end


  endfunction
  function void check_phase(uvm_phase phase);
    if(expected_quick_basic_transmit.size()!=0 || actual_quick_basic_transmit.size()!=0) `uvm_error("UNDRAINED", "quick_basic_transmit: unmatched observed transactions")
    if(expected_quick_basic_receive.size()!=0 || actual_quick_basic_receive.size()!=0) `uvm_error("UNDRAINED", "quick_basic_receive: unmatched observed transactions")
    if(comparisons < minimum_comparisons)
      `uvm_error("NO_COMPARISON", $sformatf("only %0d comparisons; require %0d", comparisons, minimum_comparisons))
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("SCOREBOARD_SUMMARY", $sformatf("comparisons=%0d", comparisons), UVM_LOW)
  endfunction
endclass
