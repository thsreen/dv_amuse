// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.

  class reset_pulse_seq extends uvm_sequence #(reset_item);
    `uvm_object_utils(reset_pulse_seq)
    reset_cfg cfg;
    function new(string name = "reset_pulse_seq");
      super.new(name);
    endfunction

    task body();
      reset_item item;
      if (cfg == null)
        `uvm_fatal("RESET_CFG", "set sequence cfg explicitly before start")
      cfg.validate();
      item = reset_item::type_id::create("assert_reset");
      start_item(item);
      item.asserted = 1;
      item.hold_time = cfg.assert_time;
      finish_item(item);
      item = reset_item::type_id::create("release_reset");
      start_item(item);
      item.asserted = 0;
      item.hold_time = 0;
      finish_item(item);
    endtask
  endclass
