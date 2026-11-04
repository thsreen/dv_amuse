// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_reset_state_seq_lcr_reset extends uvm_sequence #(cg_item);
  `uvm_object_utils(t_reset_state_seq_lcr_reset)

  function new(string name="t_reset_state_seq_lcr_reset"); super.new(name); endfunction
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
