// Model-written hook, NOT compiled into this testbench.
// target interrupt_output, slot monitor.body: Observe int_o assertion negation for interrupt scoreboard
cg_item tr;
bit last_int_o;
// IIR bit0 0 means interrupt pending asserted with INT_O, 1 means no pending
// CTS/DSR/RI/DCD change produces Modem Status interrupt observed via INT_O
last_int_o = cfg.vif.int_o;
tr = cg_item::type_id::create("int_o_tr");
tr.data = longint'(last_int_o);
tr.address = 0;
tr.mask = 1;
tr.kind = int'(last_int_o);
tr.cycles = 0;
tr.origin = "interrupt_output";
tr.error = 1'b0;
tr.data_bits = 1;
tr.parity_mode = 0;
tr.stop_bits = 1;
ap.write(tr);
forever begin
  @(cfg.vif.int_o);
  if (cfg.vif.int_o !== last_int_o) begin
    last_int_o = cfg.vif.int_o;
    tr = cg_item::type_id::create("int_o_tr");
    tr.data = longint'(last_int_o);
    tr.address = 0;
    tr.mask = 1;
    tr.kind = int'(last_int_o);
    tr.cycles = 0;
    tr.origin = "interrupt_output";
    tr.error = 1'b0;
    tr.data_bits = 1;
    tr.parity_mode = 0;
    tr.stop_bits = 1;
    ap.write(tr);
  end
end
