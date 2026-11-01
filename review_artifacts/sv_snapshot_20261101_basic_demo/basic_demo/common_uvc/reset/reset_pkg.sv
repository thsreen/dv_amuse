// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
package reset_pkg;
  timeunit 1ns;
  timeprecision 1ps;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  `include "reset_cfg.svh"
  `include "reset_item.svh"
  `include "reset_sequencer.svh"
  `include "reset_driver.svh"
  `include "reset_monitor.svh"
  `include "reset_agent.svh"
  `include "reset_pulse_seq.svh"
endpackage : reset_pkg
