// Model-written hook, NOT compiled into this testbench.
// target modem_control_if, slot driver.body: Drive CTS DSR RI DCD toggles for modem_000 stimulus via custom body
cfg.vif.cts_pad_i = req.data[0];
cfg.vif.dsr_pad_i = req.data[1];
cfg.vif.ri_pad_i = req.data[2];
cfg.vif.dcd_pad_i = req.data[3];
if (req.cycles > 0) begin repeat (req.cycles) #1; end
else begin #1; end
