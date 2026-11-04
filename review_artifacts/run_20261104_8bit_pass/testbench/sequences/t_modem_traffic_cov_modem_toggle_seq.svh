// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_modem_traffic_cov_modem_toggle_seq extends t_modem_irq_modem_toggle_seq;
  `uvm_object_utils(t_modem_traffic_cov_modem_toggle_seq)
  `uvm_declare_p_sequencer(modem_control_if_sequencer)
  function new(string name="t_modem_traffic_cov_modem_toggle_seq"); super.new(name); endfunction
  task body();
    cg_item tr;
    super.body();
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=5; tr.address=64'h0; tr.mask=64'hf; tr.cycles=2;
      tr.data=p_sequencer.t_modem_traffic_cov_modem_lvl;
      finish_item(tr);
    end
  endtask
endclass
