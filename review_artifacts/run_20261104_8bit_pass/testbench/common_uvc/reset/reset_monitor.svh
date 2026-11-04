// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.

  class reset_monitor extends uvm_component;
    `uvm_component_utils(reset_monitor)
    reset_cfg cfg;
    uvm_analysis_port #(reset_item) ap;
    function new(string name, uvm_component parent);
      super.new(name, parent);
      ap = new("ap", this);
    endfunction

    task run_phase(uvm_phase phase);
      reset_item item;
      if (cfg == null)
        `uvm_fatal("RESET_CFG", "reset monitor configuration is missing")
      cfg.validate();
      forever begin
        if (cfg.vif.reset !== 1'b0 && cfg.vif.reset !== 1'b1) begin
          `uvm_warning("RESET_X", "reset has an unknown value")
        end else begin
          item = reset_item::type_id::create("item");
          item.asserted = (cfg.vif.reset == cfg.active_level);
          item.hold_time = 0;
          ap.write(item);
        end
        @(cfg.vif.reset);
      end
    endtask
  endclass
