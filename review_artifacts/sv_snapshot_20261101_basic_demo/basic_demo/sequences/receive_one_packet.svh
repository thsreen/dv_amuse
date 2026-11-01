// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class receive_one_packet extends uvm_sequence #(cg_item);
  `uvm_object_utils(receive_one_packet)

  function new(string name="receive_one_packet"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=3; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h5a;
      finish_item(tr);
    end
  endtask
endclass
