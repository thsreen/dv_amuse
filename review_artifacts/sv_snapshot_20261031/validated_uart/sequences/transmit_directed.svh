class transmit_directed extends uvm_sequence #(cg_item);
  `uvm_object_utils(transmit_directed)

  function new(string name="transmit_directed"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'ha5;
      finish_item(tr);
    end
  endtask
endclass
