class uart_serial_data_monitor extends uvm_component;
  `uvm_component_utils(uart_serial_data_monitor)
  uart_serial_data_cfg cfg;
  uvm_analysis_port #(cg_item) ap;
  function new(string name, uvm_component parent); super.new(name,parent); ap=new("ap",this); endfunction
  task sample_line(bit transmit);
    forever begin
      bit prior;
      logic current;
      bit parity;
      bit aborted;
      logic [63:0] sampled_data;
      cg_item tr;
      prior=1;
      do begin
        @(posedge cfg.vif.clk);
        current=transmit ? cfg.vif.tx : cfg.vif.rx;
        if (cfg.vif.reset == cfg.reset_active) prior=1;
        else if ($isunknown(transmit ? cfg.vif.tx : cfg.vif.rx)) `uvm_error("MON_X", "unknown serial line")
        if(cfg.vif.reset != cfg.reset_active && prior && !current) break;
        prior=current;
      end while(1);
      repeat(cfg.bit_cycles/2) @(posedge cfg.vif.clk);
      if((transmit ? cfg.vif.tx : cfg.vif.rx) !== 1'b0) continue;
      tr=cg_item::type_id::create("frame"); tr.origin="uart_serial_data"; tr.kind=transmit ? 4 : 3;
      tr.data_bits=cfg.data_bits; tr.parity_mode=cfg.parity_mode; tr.stop_bits=cfg.stop_bits;
      sampled_data=0; parity=0; aborted=0;
      for(int i=0;i<cfg.data_bits;i++) begin
        repeat(cfg.bit_cycles) @(posedge cfg.vif.clk);
        if(cfg.vif.reset == cfg.reset_active) aborted=1;
        if($isunknown(transmit ? cfg.vif.tx : cfg.vif.rx)) `uvm_error("MON_X", "unknown serial data bit")
        sampled_data[i]=transmit ? cfg.vif.tx : cfg.vif.rx; parity ^= sampled_data[i];
      end
      if(cfg.parity_mode != 0) begin
        repeat(cfg.bit_cycles) @(posedge cfg.vif.clk);
        current=transmit ? cfg.vif.tx : cfg.vif.rx;
        tr.error=(current !== ((cfg.parity_mode==1) ? parity : !parity));
        if(cfg.vif.reset == cfg.reset_active) aborted=1;
      end
      repeat(cfg.stop_bits) begin
        repeat(cfg.bit_cycles) @(posedge cfg.vif.clk);
        if((transmit ? cfg.vif.tx : cfg.vif.rx) !== 1'b1) tr.error=1;
        if(cfg.vif.reset == cfg.reset_active) aborted=1;
      end
      tr.data=sampled_data;
      if(!aborted) ap.write(tr);
    end
  endtask
  task run_phase(uvm_phase phase);
    fork sample_line(0); sample_line(1); join
  endtask
endclass
