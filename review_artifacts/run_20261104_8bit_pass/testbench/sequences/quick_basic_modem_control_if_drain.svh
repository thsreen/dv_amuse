// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
class quick_basic_modem_control_if_drain extends uvm_sequence #(cg_item);
  `uvm_object_utils(quick_basic_modem_control_if_drain)

  function new(string name="quick_basic_modem_control_if_drain"); super.new(name); endfunction
  task body();
    cg_item tr;
    tr=cg_item::type_id::create("drain"); start_item(tr); tr.kind=0; tr.cycles=384; finish_item(tr);
  endtask
endclass
