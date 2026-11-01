// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class collect_received_packet extends uvm_sequence #(cg_item);
  `uvm_object_utils(collect_received_packet)

  function new(string name="collect_received_packet"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=6; tr.address=64'h5; tr.mask=64'h1; tr.cycles=0;
      tr.data=64'h1;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
  endtask
endclass
