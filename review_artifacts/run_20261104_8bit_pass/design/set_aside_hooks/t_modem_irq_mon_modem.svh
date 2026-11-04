// Model-written hook, NOT compiled into this testbench.
// target modem_control_if, slot monitor.body: Observe CTS DSR RI DCD toggles and RTS DTR for scoreboard
cg_item mon_item;
logic prev_cts;
logic prev_dsr;
logic prev_ri;
logic prev_dcd;
logic prev_rts;
logic prev_dtr;
prev_cts = cfg.vif.cts_pad_i;
prev_dsr = cfg.vif.dsr_pad_i;
prev_ri = cfg.vif.ri_pad_i;
prev_dcd = cfg.vif.dcd_pad_i;
prev_rts = cfg.vif.rts_pad_o;
prev_dtr = cfg.vif.dtr_pad_o;
forever begin
  @(cfg.vif.cts_pad_i or cfg.vif.dsr_pad_i or cfg.vif.ri_pad_i or cfg.vif.dcd_pad_i or cfg.vif.rts_pad_o or cfg.vif.dtr_pad_o);
  mon_item = cg_item::type_id::create("mon_item");
  mon_item.origin = "modem";
  mon_item.kind = 0;
  mon_item.data = {58'd0, cfg.vif.rts_pad_o, cfg.vif.dtr_pad_o, cfg.vif.cts_pad_i, cfg.vif.dsr_pad_i, cfg.vif.ri_pad_i, cfg.vif.dcd_pad_i};
  mon_item.mask = {60'd0, (cfg.vif.cts_pad_i !== prev_cts), (cfg.vif.dsr_pad_i !== prev_dsr), (cfg.vif.ri_pad_i !== prev_ri), (cfg.vif.dcd_pad_i !== prev_dcd)};
  mon_item.address = 0;
  mon_item.cycles = 0;
  mon_item.error = 1'b0;
  mon_item.data_bits = 8;
  mon_item.parity_mode = 0;
  mon_item.stop_bits = 1;
  ap.write(mon_item);
  prev_cts = cfg.vif.cts_pad_i;
  prev_dsr = cfg.vif.dsr_pad_i;
  prev_ri = cfg.vif.ri_pad_i;
  prev_dcd = cfg.vif.dcd_pad_i;
  prev_rts = cfg.vif.rts_pad_o;
  prev_dtr = cfg.vif.dtr_pad_o;
end
