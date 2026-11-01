// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
module register_bus_assertions(register_bus_if bus);
  property p_bus_known; @(posedge bus.clk) disable iff (bus.reset == 1) (bus.cyc && bus.stb) |-> (!$isunknown({bus.addr,bus.sel,bus.we,bus.ack})); endproperty
  a_bus_known: assert property(p_bus_known) else $error("bus_known");
  c_bus_known: cover property(p_bus_known);
  activation_bus_known: cover property(@(posedge bus.clk) disable iff (bus.reset == 1) bus.cyc && bus.stb);
endmodule
