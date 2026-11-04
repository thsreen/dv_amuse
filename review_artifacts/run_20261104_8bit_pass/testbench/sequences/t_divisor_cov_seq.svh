// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_divisor_cov_seq extends t_wb_init_cfg_init_seq;
  `uvm_object_utils(t_divisor_cov_seq)
  `uvm_declare_p_sequencer(wishbone_slave_interface_sequencer)
  function new(string name="t_divisor_cov_seq"); super.new(name); endfunction
  task body();
    cg_item tr;
    super.body();
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_lcr",64'h80,0);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_divisor_cov_msb",64'h0,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_divisor_cov_msb",64'h1,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h1;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_divisor_cov_msb",p_sequencer.t_divisor_cov_mid_low,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=p_sequencer.t_divisor_cov_mid_low;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_divisor_cov_msb",p_sequencer.t_divisor_cov_mid_high,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=p_sequencer.t_divisor_cov_mid_high;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_divisor_cov_msb",64'hff,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'hff;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_divisor_cov_msb",64'hff,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_divisor_cov_msb",64'h0,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'hff;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_lcr",64'h0,0);
    end
  endtask
endclass
