class initialize_link extends uvm_sequence #(cg_item);
  `uvm_object_utils(initialize_link)

  function new(string name="initialize_link"); super.new(name); endfunction
  task body();
    cg_item tr;
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h3; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h83;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h1; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h0; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h2;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h3; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h3;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h1; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h0;
      finish_item(tr);
    end
    repeat(1) begin
      tr=cg_item::type_id::create("request");
      start_item(tr);
      tr.kind=1; tr.address=64'h2; tr.mask=64'hff; tr.cycles=0;
      tr.data=64'h6;
      finish_item(tr);
    end
  endtask
endclass
