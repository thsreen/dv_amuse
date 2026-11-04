// Model-written hook, NOT compiled into this testbench.
// target interrupt_output, slot monitor.body: Passively observe int_o levels timestamped for pending correlation never drive
cg_item tr;
forever begin
  tr = cg_item::type_id::create("mon_int_tr");
  tr.data = longint'(cfg.vif.int_o);
  tr.address = 0;
  tr.mask = 0;
  tr.kind = 0;
  tr.cycles = int'($time);
  tr.origin = "interrupt_output";
  tr.error = 0;
  tr.data_bits = 1;
  tr.parity_mode = 0;
  tr.stop_bits = 0;
  ap.write(tr);
  @(cfg.vif.int_o);
end
