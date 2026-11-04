// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class modem_control_if_driver extends uvm_driver #(cg_item);
  `uvm_component_utils(modem_control_if_driver)
  modem_control_if_cfg cfg;
  function new(string name, uvm_component parent); super.new(name,parent); endfunction
  virtual function void drive_reset_values();
    cfg.vif.CTS_PAD_I = 64'h0;
    cfg.vif.DSR_PAD_I = 64'h0;
    cfg.vif.RI_PAD_I = 64'h0;
    cfg.vif.DCD_PAD_I = 64'h0;
  endfunction
  virtual task drive_item(cg_item tr);
    repeat (tr.cycles) @(posedge cfg.vif.clk);
  endtask
  task run_phase(uvm_phase phase);
    drive_reset_values();
    forever begin
      seq_item_port.get_next_item(req);
      drive_item(req);
      seq_item_port.item_done();
    end
  endtask
endclass
