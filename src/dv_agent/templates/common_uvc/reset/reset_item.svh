
  class reset_item extends uvm_sequence_item;
    `uvm_object_utils(reset_item)
    bit asserted;
    realtime hold_time;
    function new(string name = "reset_item");
      super.new(name);
    endfunction
  endclass
