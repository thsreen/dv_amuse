class check_configuration extends uvm_sequence #(cg_item);
  `uvm_object_utils(check_configuration)

  function new(string name="check_configuration"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h3; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
  endtask
endclass
