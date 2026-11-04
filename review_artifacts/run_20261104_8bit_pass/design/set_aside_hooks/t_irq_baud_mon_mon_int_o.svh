// Model-written hook, NOT compiled into this testbench.
// target interrupt_output, slot monitor.body: Sample int_o each wb_clk_i edge without driving; emit timestamped edge event; clear pending and restart base on reset
cg_item evt;
bit prev_int_o;
longint unsigned tick_cnt;
tick_cnt = 0;
prev_int_o = 1'b0;
evt = null;
forever begin
  @(posedge cfg.vif.wb_clk_i or posedge cfg.vif.wb_rst_i);
  if (cfg.vif.wb_rst_i) begin
    tick_cnt = 0;
    prev_int_o = 1'b0;
    evt = null;
  end else begin
    tick_cnt++;
    if (cfg.vif.int_o !== prev_int_o) begin
      evt = cg_item::type_id::create("int_o_evt");
      evt.data = (longint'(cfg.vif.int_o) & 64'h1);
      evt.address = 0;
      evt.mask = 0;
      evt.kind = 0;
      evt.cycles = tick_cnt;
      evt.origin = "int_o";
      evt.error = 1'b0;
      evt.data_bits = 1;
      evt.parity_mode = 0;
      evt.stop_bits = 0;
      ap.write(evt);
      evt = null;
      prev_int_o = cfg.vif.int_o;
    end
  end
end
