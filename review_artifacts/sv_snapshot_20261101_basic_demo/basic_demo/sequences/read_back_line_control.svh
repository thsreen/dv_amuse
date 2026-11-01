// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class read_back_line_control extends uvm_sequence #(cg_item);
  `uvm_object_utils(read_back_line_control)

  function new(string name="read_back_line_control"); super.new(name); endfunction
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
