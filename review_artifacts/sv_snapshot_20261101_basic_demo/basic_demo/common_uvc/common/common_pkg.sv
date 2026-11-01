// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
package common_pkg;
  timeunit 1ns;
  timeprecision 1ps;
  import uvm_pkg::*;
  import clock_pkg::*;
  import reset_pkg::*;
  `include "uvm_macros.svh"

  `include "common_cfg.svh"
  `include "common_agent.svh"
  `include "common_env.svh"
endpackage : common_pkg
