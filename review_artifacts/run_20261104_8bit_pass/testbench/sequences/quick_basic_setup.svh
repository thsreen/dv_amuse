// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class quick_basic_setup extends uvm_sequence #(cg_item);
  `uvm_object_utils(quick_basic_setup)

  function new(string name="quick_basic_setup"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_lcr",64'h83,0);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_divisor_cov_msb",64'h0,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h1;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_lcr",64'h3,0);
    end
  endtask
endclass
