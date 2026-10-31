package clock_pkg;
  timeunit 1ns;
  timeprecision 1ps;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  `include "clock_cfg.svh"
  `include "clock_tick.svh"
  `include "clock_driver.svh"
  `include "clock_monitor.svh"
  `include "clock_agent.svh"
endpackage : clock_pkg
