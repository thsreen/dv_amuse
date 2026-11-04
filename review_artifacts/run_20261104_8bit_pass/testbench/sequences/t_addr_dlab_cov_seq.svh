// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_addr_dlab_cov_seq extends t_dlab_gate_chk_seq;
  `uvm_object_utils(t_addr_dlab_cov_seq)
  `uvm_declare_p_sequencer(wishbone_slave_interface_sequencer)
  function new(string name="t_addr_dlab_cov_seq"); super.new(name); endfunction
  task body();
    cg_item tr;
    super.body();
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_lcr",p_sequencer.t_addr_dlab_cov_lcr_dlab1,0);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_fcr",p_sequencer.t_addr_dlab_cov_fcr_byte,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h2; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h3; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_traffic_seq_mcr",p_sequencer.t_addr_dlab_cov_mcr_byte,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h5; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h6; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h7; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h7; tr.mask=64'hff; tr.cycles=0;
      tr.data=p_sequencer.t_addr_dlab_cov_payload;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_lcr",p_sequencer.t_addr_dlab_cov_lcr_dlab0,0);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_fcr",p_sequencer.t_addr_dlab_cov_fcr_byte,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h2; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h3; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_traffic_seq_mcr",p_sequencer.t_addr_dlab_cov_mcr_byte,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h5; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h6; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=2; tr.address=64'h7; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h7; tr.mask=64'hff; tr.cycles=0;
      tr.data=p_sequencer.t_addr_dlab_cov_payload;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_lcr",p_sequencer.t_addr_dlab_cov_lcr_dlab0,0);
    end
  endtask
endclass
