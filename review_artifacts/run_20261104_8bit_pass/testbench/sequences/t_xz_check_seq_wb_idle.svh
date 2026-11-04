// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_xz_check_seq_wb_idle extends uvm_sequence #(cg_item);
  `uvm_object_utils(t_xz_check_seq_wb_idle)

  function new(string name="t_xz_check_seq_wb_idle"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=0; tr.address=64'h0; tr.mask=64'hff; tr.cycles=16;
      tr.data=64'h0;
      finish_item(tr);
    end
  endtask
endclass
