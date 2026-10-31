class random_transmit_register_bus_drain extends uvm_sequence #(cg_item);
  `uvm_object_utils(random_transmit_register_bus_drain)

  function new(string name="random_transmit_register_bus_drain"); super.new(name); endfunction
  task body();
    cg_item tr;
    tr=cg_item::type_id::create("drain"); start_item(tr); tr.kind=0; tr.cycles=4096; finish_item(tr);
  endtask
endclass
