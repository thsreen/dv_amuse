// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.

  class clock_monitor extends uvm_component;
    `uvm_component_utils(clock_monitor)
    clock_cfg cfg;
    uvm_analysis_port #(clock_tick) ap;
    function new(string name, uvm_component parent);
      super.new(name, parent);
      ap = new("ap", this);
    endfunction

    task run_phase(uvm_phase phase);
      clock_tick tick;
      realtime previous_time;
      bit have_previous;
      if (cfg == null || cfg.vif == null)
        `uvm_fatal("CLOCK_VIF", "clock monitor configuration is missing")
      forever begin
        @(posedge cfg.vif.clk);
        tick = clock_tick::type_id::create("tick");
        tick.at_time = $realtime;
        tick.period_since_last = have_previous ? ($realtime - previous_time) : 0;
        previous_time = $realtime;
        have_previous = 1;
        ap.write(tick);
      end
    endtask
  endclass
