
  class reset_pulse_seq extends uvm_sequence #(reset_item);
    `uvm_object_utils(reset_pulse_seq)
    `uvm_declare_p_sequencer(reset_sequencer)
    function new(string name = "reset_pulse_seq");
      super.new(name);
    endfunction

    task body();
      reset_item item;
      if (p_sequencer.cfg == null)
        `uvm_fatal("RESET_CFG", "reset sequencer configuration is missing")
      p_sequencer.cfg.validate();
      item = reset_item::type_id::create("assert_reset");
      start_item(item);
      item.asserted = 1;
      item.hold_time = p_sequencer.cfg.assert_time;
      finish_item(item);
      item = reset_item::type_id::create("release_reset");
      start_item(item);
      item.asserted = 0;
      item.hold_time = 0;
      finish_item(item);
    endtask
  endclass
