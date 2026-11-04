// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class quick_basic_send extends uvm_sequence #(cg_item);
  `uvm_object_utils(quick_basic_send)

  function new(string name="quick_basic_send"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=3; tr.address=64'h0; tr.mask=64'hff; tr.cycles=192;
      tr.data=64'ha5;
      finish_item(tr);
    end
  endtask
endclass
