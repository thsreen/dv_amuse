// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_modem_irq_virt_seq extends t_traffic_seq_normal_virt;
  `uvm_object_utils(t_modem_irq_virt_seq)

  function new(string name="t_modem_irq_virt_seq"); super.new(name); endfunction
  task body();
    cg_item tr;
    super.body();
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=0; tr.address=64'h0; tr.mask=64'h0; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
  endtask
endclass
