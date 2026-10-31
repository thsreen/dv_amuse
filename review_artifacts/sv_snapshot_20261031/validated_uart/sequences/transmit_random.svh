class transmit_random extends uvm_sequence #(cg_item);
  `uvm_object_utils(transmit_random)

  function new(string name="transmit_random"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=6; tr.address=64'h5; tr.mask=64'h20; tr.cycles=0;
      tr.data=64'h20;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      if(!tr.randomize()) `uvm_fatal("RAND", "randomization failed")
      tr.data &= 64'hff;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=6; tr.address=64'h5; tr.mask=64'h20; tr.cycles=0;
      tr.data=64'h20;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      if(!tr.randomize()) `uvm_fatal("RAND", "randomization failed")
      tr.data &= 64'hff;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=6; tr.address=64'h5; tr.mask=64'h20; tr.cycles=0;
      tr.data=64'h20;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      if(!tr.randomize()) `uvm_fatal("RAND", "randomization failed")
      tr.data &= 64'hff;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=6; tr.address=64'h5; tr.mask=64'h20; tr.cycles=0;
      tr.data=64'h20;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      if(!tr.randomize()) `uvm_fatal("RAND", "randomization failed")
      tr.data &= 64'hff;
      finish_item(tr);
    end
  endtask
endclass
