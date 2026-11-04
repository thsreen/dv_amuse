// Model-written hook, NOT compiled into this testbench.
// target modem_control_if, slot monitor.body: Sample modem control pads for XZ
forever begin
  @(posedge cfg.vif.clk);
  begin
    automatic cg_item m_item = cg_item::type_id::create("m_item");
    automatic logic rts_v = cfg.vif.rts_pad_o;
    automatic logic dtr_v = cfg.vif.dtr_pad_o;
    automatic logic cts_v = cfg.vif.cts_pad_i;
    automatic logic dsr_v = cfg.vif.dsr_pad_i;
    automatic logic ri_v = cfg.vif.ri_pad_i;
    automatic logic dcd_v = cfg.vif.dcd_pad_i;
    m_item.origin = "modem_control_if";
    m_item.kind = 0;
    m_item.cycles = 1;
    m_item.address = 0;
    m_item.mask = 0;
    m_item.data = {26'd0, rts_v, dtr_v, cts_v, dsr_v, ri_v, dcd_v};
    m_item.data_bits = 6;
    m_item.parity_mode = 0;
    m_item.stop_bits = 1;
    m_item.error = $isunknown({rts_v, dtr_v, cts_v, dsr_v, ri_v, dcd_v});
    ap.write(m_item);
  end
end
