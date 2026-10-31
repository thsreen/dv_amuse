
  class reset_driver extends uvm_driver #(reset_item);
    `uvm_component_utils(reset_driver)
    reset_cfg cfg;
    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    virtual task drive_item(reset_item tr);
      cfg.vif.reset = tr.asserted ? cfg.active_level : !cfg.active_level;
      if (tr.hold_time > 0)
        #(tr.hold_time);
    endtask

    task run_phase(uvm_phase phase);
      cfg.validate();
      cfg.vif.reset = cfg.active_level;
      forever begin
        seq_item_port.get_next_item(req);
        drive_item(req);
        seq_item_port.item_done();
      end
    endtask
  endclass
