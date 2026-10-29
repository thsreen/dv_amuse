
  class clock_tick extends uvm_sequence_item;
    `uvm_object_utils(clock_tick)
    time at_time;
    time period_since_last;
    function new(string name = "clock_tick");
      super.new(name);
    endfunction
  endclass
