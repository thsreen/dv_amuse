// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class cg_scoreboard extends uvm_subscriber #(cg_item);
  `uvm_component_utils(cg_scoreboard)
  virtual reset_if reset_vif;
  bit reset_active;
  int unsigned comparisons;
  int unsigned minimum_comparisons=1;
  longint unsigned qualification_transmit_path_0;
  bit qualification_transmit_path_0_valid;
  longint unsigned mirror_line_control;
  bit valid_line_control;
  longint unsigned mirror_data_or_divisor_low;
  bit valid_data_or_divisor_low;
  longint unsigned mirror_interrupt_enable_or_divisor_high;
  bit valid_interrupt_enable_or_divisor_high;
  longint unsigned mirror_fifo_control;
  bit valid_fifo_control;
  longint unsigned expected_transmit_path[$], actual_transmit_path[$];
  longint unsigned expected_receive_path[$], actual_receive_path[$];
  function new(string name, uvm_component parent); super.new(name,parent); endfunction
  function void flush();
    qualification_transmit_path_0=64'h3; qualification_transmit_path_0_valid=1;
    mirror_line_control=64'h3; valid_line_control=1;
    mirror_data_or_divisor_low=64'h0; valid_data_or_divisor_low=0;
    mirror_interrupt_enable_or_divisor_high=64'h0; valid_interrupt_enable_or_divisor_high=0;
    mirror_fifo_control=64'h0; valid_fifo_control=0;
    expected_transmit_path.delete(); actual_transmit_path.delete();
    expected_receive_path.delete(); actual_receive_path.delete();
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
    if(tr.origin=="register_bus" && tr.address==64'h3) begin
      if(tr.kind==1) begin mirror_line_control=(mirror_line_control & ~64'hff) | (tr.data & 64'hff); valid_line_control=1; end
      if(tr.kind==2 && valid_line_control) begin comparisons++;
        if((tr.data & 64'hff) != (mirror_line_control & 64'hff)) `uvm_error("REGISTER_MISMATCH", "line_control")
      end
    end
    if(tr.origin=="register_bus" && tr.address==64'h0) begin
      if(tr.kind==1) begin mirror_data_or_divisor_low=(mirror_data_or_divisor_low & ~64'hff) | (tr.data & 64'hff); valid_data_or_divisor_low=1; end
    end
    if(tr.origin=="register_bus" && tr.address==64'h1) begin
      if(tr.kind==1) begin mirror_interrupt_enable_or_divisor_high=(mirror_interrupt_enable_or_divisor_high & ~64'hff) | (tr.data & 64'hff); valid_interrupt_enable_or_divisor_high=1; end
    end
    if(tr.origin=="register_bus" && tr.address==64'h2) begin
      if(tr.kind==1) begin mirror_fifo_control=(mirror_fifo_control & ~64'hff) | (tr.data & 64'hff); valid_fifo_control=1; end
    end
    if(tr.origin=="register_bus" && tr.kind==1 && tr.address==64'h3) begin qualification_transmit_path_0=tr.data; qualification_transmit_path_0_valid=1; end
    if(tr.origin=="register_bus" && tr.kind==1 && tr.address==64'h0 && (qualification_transmit_path_0_valid && (qualification_transmit_path_0 & 64'h80)==64'h0)) expected_transmit_path.push_back(tr.data & 64'hff);
    if(tr.origin=="serial_link" && tr.kind==4 && (qualification_transmit_path_0_valid && (qualification_transmit_path_0 & 64'h80)==64'h0)) actual_transmit_path.push_back(tr.data & 64'hff);
    while(expected_transmit_path.size()!=0 && actual_transmit_path.size()!=0) begin
      longint unsigned e, a; e=expected_transmit_path.pop_front(); a=actual_transmit_path.pop_front(); comparisons++;
      if(e != a) `uvm_error("DATA_MISMATCH", $sformatf("transmit_path: expected=%h actual=%h", e,a))
    end
    if(tr.origin=="serial_link" && tr.kind==3) expected_receive_path.push_back(tr.data & 64'hff);
    if(tr.origin=="register_bus" && tr.kind==2 && tr.address==64'h0) actual_receive_path.push_back(tr.data & 64'hff);
    while(expected_receive_path.size()!=0 && actual_receive_path.size()!=0) begin
      longint unsigned e, a; e=expected_receive_path.pop_front(); a=actual_receive_path.pop_front(); comparisons++;
      if(e != a) `uvm_error("DATA_MISMATCH", $sformatf("receive_path: expected=%h actual=%h", e,a))
    end


  endfunction
  function void check_phase(uvm_phase phase);
    if(expected_transmit_path.size()!=0 || actual_transmit_path.size()!=0) `uvm_error("UNDRAINED", "transmit_path: unmatched observed transactions")
    if(expected_receive_path.size()!=0 || actual_receive_path.size()!=0) `uvm_error("UNDRAINED", "receive_path: unmatched observed transactions")
    if(comparisons < minimum_comparisons)
      `uvm_error("NO_COMPARISON", $sformatf("only %0d comparisons; require %0d", comparisons, minimum_comparisons))
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("SCOREBOARD_SUMMARY", $sformatf("comparisons=%0d", comparisons), UVM_LOW)
  endfunction
endclass
