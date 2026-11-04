class wishbone_slave_interface_driver extends uvm_driver #(cg_item);
  `uvm_component_utils(wishbone_slave_interface_driver)
  wishbone_slave_interface_cfg cfg;
  function new(string name, uvm_component parent); super.new(name, parent); endfunction
  virtual function void drive_reset_values();
    cfg.vif.addr = 64'h0;
    cfg.vif.wdata = 64'h0;
    cfg.vif.we = 64'h0;
    cfg.vif.stb = 64'h0;
    cfg.vif.cyc = 64'h0;
    cfg.vif.sel = '0;
  endfunction
  task run_phase(uvm_phase phase);
    drive_reset_values();
    forever begin
      seq_item_port.get_next_item(req);
      if (req.kind == 0) repeat(req.cycles) @(posedge cfg.vif.clk);
      else begin
        int waited;
        int polls;
        bit complete;
        polls=0; complete=0;
        do begin
        @(negedge cfg.vif.clk);
        if (cfg.vif.reset == cfg.reset_active) `uvm_fatal("RESET", "bus request during reset")
        cfg.vif.addr = req.address; cfg.vif.wdata = req.data;
        cfg.vif.sel = '1; cfg.vif.we = (req.kind == 1);
        cfg.vif.cyc = 1; cfg.vif.stb = 1;
        waited = 0;
        do begin
          @(posedge cfg.vif.clk); waited++;
          if (waited >= cfg.timeout_cycles) `uvm_fatal("BUS_TIMEOUT", "testbench request deadline exceeded")
        end while (cfg.vif.ack !== 1'b1);
        complete=(req.kind!=6) || ((cfg.vif.rdata & req.mask)==req.data);
        @(negedge cfg.vif.clk); cfg.vif.cyc = 0; cfg.vif.stb = 0; cfg.vif.we = 0;
        repeat(req.cycles) @(posedge cfg.vif.clk);
        polls++;
        if(!complete && polls>=cfg.timeout_cycles) `uvm_fatal("POLL_TIMEOUT", "testbench polling deadline exceeded")
        end while(!complete);
      end
      seq_item_port.item_done();
    end
  endtask
endclass
