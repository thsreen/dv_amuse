// Model-written hook, NOT compiled into this testbench.
// target modem_control_if, slot monitor.body: Observe modem_000 versus no_modem for coverage sampling via monitor body
cg_item mon_item;
forever begin
  mon_item = cg_item::type_id::create("mon_item");
  mon_item.origin = "modem_mon";
  mon_item.data = {28'd0, cfg.vif.dcd_pad_i, cfg.vif.ri_pad_i, cfg.vif.dsr_pad_i, cfg.vif.cts_pad_i};
  mon_item.address = 0;
  mon_item.mask = 15;
  mon_item.kind = int'(mon_item.data);
  mon_item.cycles = 2;
  mon_item.error = 1'b0;
  mon_item.data_bits = 8;
  mon_item.parity_mode = 0;
  mon_item.stop_bits = 1;
  ap.write(mon_item);
  @(cfg.vif.cts_pad_i or cfg.vif.dsr_pad_i or cfg.vif.ri_pad_i or cfg.vif.dcd_pad_i);
end
