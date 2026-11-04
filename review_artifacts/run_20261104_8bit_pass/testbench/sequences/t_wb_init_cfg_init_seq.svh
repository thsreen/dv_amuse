// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_wb_init_cfg_init_seq extends uvm_sequence #(cg_item);
  `uvm_object_utils(t_wb_init_cfg_init_seq)
  `uvm_declare_p_sequencer(wishbone_slave_interface_sequencer)
  function new(string name="t_wb_init_cfg_init_seq"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_lcr",p_sequencer.t_wb_init_cfg_lcr_dlab1,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h1; tr.mask=64'hff; tr.cycles=0;
      tr.data=p_sequencer.t_wb_init_cfg_div_msb;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=p_sequencer.t_wb_init_cfg_div_lsb;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_lcr",p_sequencer.t_wb_init_cfg_lcr_dlab0,0);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_fcr",p_sequencer.t_wb_init_cfg_fcr_byte,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h1; tr.mask=64'hff; tr.cycles=0;
      tr.data=p_sequencer.t_wb_init_cfg_ier_byte;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h1; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
  endtask
endclass
