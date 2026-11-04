// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class t_uart_mon_bringup_seq extends t_wb_init_cfg_init_seq;
  `uvm_object_utils(t_uart_mon_bringup_seq)
  `uvm_declare_p_sequencer(wishbone_slave_interface_sequencer)
  function new(string name="t_uart_mon_bringup_seq"); super.new(name); endfunction
  task body();
    cg_item tr;
    super.body();
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_lcr",p_sequencer.t_uart_mon_lcr_dlab1,0);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_divisor_cov_msb",p_sequencer.t_uart_mon_div_msb,0);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=p_sequencer.t_uart_mon_div_lsb;
      finish_item(tr);
    end
    repeat(1) begin
      cg_reg_access::write(this,"t_wb_init_cfg_lcr",p_sequencer.t_uart_mon_lcr_dlab0,0);
    end
  endtask
endclass
