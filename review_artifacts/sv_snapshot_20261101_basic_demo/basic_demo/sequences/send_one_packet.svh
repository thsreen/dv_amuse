// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class send_one_packet extends uvm_sequence #(cg_item);
  `uvm_object_utils(send_one_packet)

  function new(string name="send_one_packet"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      cg_reg_access::write(this,"data_or_divisor_low",64'ha5,0);
    end
  endtask
endclass
