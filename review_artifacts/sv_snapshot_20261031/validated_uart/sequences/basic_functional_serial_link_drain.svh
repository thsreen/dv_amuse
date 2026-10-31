class basic_functional_serial_link_drain extends uvm_sequence #(cg_item);
  `uvm_object_utils(basic_functional_serial_link_drain)

  function new(string name="basic_functional_serial_link_drain"); super.new(name); endfunction
  task body();
    cg_item tr;
    tr=cg_item::type_id::create("drain"); start_item(tr); tr.kind=0; tr.cycles=2048; finish_item(tr);
  endtask
endclass
