// Model-written hook, NOT compiled into this testbench.
// target interrupt_output, slot monitor.body: Sample INT_O for XZ and known-after-reset
cg_item mon_item;
forever begin
  mon_item = cg_item::type_id::create("mon_item");
  mon_item.origin = "interrupt_output";
  mon_item.data_bits = 1;
  mon_item.data = cfg.vif.int_o;
  mon_item.error = $isunknown(cfg.vif.int_o);
  mon_item.kind = 0;
  mon_item.cycles = 0;
  mon_item.address = 0;
  mon_item.mask = 0;
  ap.write(mon_item);
  @(cfg.vif.int_o);
end
