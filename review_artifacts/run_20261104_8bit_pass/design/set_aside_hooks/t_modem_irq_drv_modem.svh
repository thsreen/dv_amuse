// Model-written hook, NOT compiled into this testbench.
// target modem_control_if, slot driver.body: Drive single toggle via modem_handshake_toggle test only infrastructure
cfg.vif.cts_pad_i <= ~cfg.vif.cts_pad_i;
repeat (req.cycles + req.data[0] + 1) #1;
