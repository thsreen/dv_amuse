// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class configure_link extends uvm_sequence #(cg_item);
  `uvm_object_utils(configure_link)

  function new(string name="configure_link"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      cg_reg_access::write(this,"line_control",64'h83,0);
    end
    repeat(1) begin
      cg_reg_access::write(this,"interrupt_enable_or_divisor_high",64'h0,0);
    end
    repeat(1) begin
      cg_reg_access::write(this,"data_or_divisor_low",64'h2,0);
    end
    repeat(1) begin
      cg_reg_access::write(this,"line_control",64'h3,0);
    end
    repeat(1) begin
      cg_reg_access::write(this,"interrupt_enable_or_divisor_high",64'h0,0);
    end
    repeat(1) begin
      cg_reg_access::write(this,"fifo_control",64'h6,0);
    end
  endtask
endclass
