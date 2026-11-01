// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class serial_link_driver extends uvm_driver #(cg_item);
  `uvm_component_utils(serial_link_driver)
  serial_link_cfg cfg;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  task bit_time(); repeat(cfg.bit_cycles) @(negedge cfg.vif.clk); endtask
  virtual function void drive_reset_values();
    cfg.vif.rx = 64'h1;
  endfunction
  task run_phase(uvm_phase phase);
    drive_reset_values();
    forever begin
      seq_item_port.get_next_item(req);
      if (req.kind == 0) repeat(req.cycles) @(posedge cfg.vif.clk);
      else begin
        bit parity;
        @(negedge cfg.vif.clk);
        if (cfg.vif.reset == cfg.reset_active) `uvm_fatal("RESET", "serial request during reset")
        cfg.vif.rx=0; bit_time(); parity=0;
        for(int i=0;i<cfg.data_bits;i++) begin cfg.vif.rx=req.data[i]; parity ^= req.data[i]; bit_time(); end
        if(cfg.parity_mode != 0) begin
          cfg.vif.rx=(cfg.parity_mode==1) ? parity : !parity; bit_time();
        end
        cfg.vif.rx=1; repeat(cfg.stop_bits) bit_time();
        repeat(req.cycles) @(posedge cfg.vif.clk);
      end
      seq_item_port.item_done();
    end
  endtask
endclass
