// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_modem_traffic_cov_wb_bringup_seq extends t_modem_irq_wb_bringup_seq;
  `uvm_object_utils(t_modem_traffic_cov_wb_bringup_seq)
  `uvm_declare_p_sequencer(wishbone_slave_interface_sequencer)
  function new(string name="t_modem_traffic_cov_wb_bringup_seq"); super.new(name); endfunction
  task body();
    cg_item tr;
    super.body();
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h1; tr.mask=64'hff; tr.cycles=0;
      tr.data=p_sequencer.t_modem_traffic_cov_ier_en;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h1; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=0; tr.address=64'h0; tr.mask=64'h0; tr.cycles=32;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h2; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
  endtask
endclass
