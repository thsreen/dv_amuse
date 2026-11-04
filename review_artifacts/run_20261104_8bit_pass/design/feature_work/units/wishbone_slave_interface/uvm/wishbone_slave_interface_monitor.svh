class wishbone_slave_interface_monitor extends uvm_component;
  `uvm_component_utils(wishbone_slave_interface_monitor)
  wishbone_slave_interface_cfg cfg;
  uvm_analysis_port #(cg_item) ap;
  function new(string name, uvm_component parent); super.new(name, parent); ap=new("ap",this); endfunction
  task run_phase(uvm_phase phase);
    forever begin
      @(posedge cfg.vif.clk);
      if (cfg.vif.reset != cfg.reset_active && cfg.vif.cyc && cfg.vif.stb) begin
        if ($isunknown({cfg.vif.we,cfg.vif.addr,cfg.vif.sel,cfg.vif.ack}))
          `uvm_error("MON_X", "unknown bus control sampled")
        if (cfg.vif.ack === 1'b1) begin
          cg_item tr = cg_item::type_id::create("observed");
          tr.origin="wishbone_slave_interface"; tr.kind=cfg.vif.we ? 1 : 2;
          tr.address=cfg.vif.addr; tr.data=cfg.vif.we ? cfg.vif.wdata : cfg.vif.rdata;
          if ($isunknown(cfg.vif.we ? cfg.vif.wdata : cfg.vif.rdata))
            `uvm_error("MON_X", "unknown bus payload sampled")
          tr.data_bits=8; ap.write(tr);
        end
      end
    end
  endtask
endclass
