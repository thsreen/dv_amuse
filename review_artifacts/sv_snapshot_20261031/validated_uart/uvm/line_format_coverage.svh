class line_format_coverage extends uvm_subscriber #(cg_item);
  `uvm_component_utils(line_format_coverage)
  cg_item observed;
  int unsigned samples;
  longint unsigned sampled_word_length;
  longint unsigned sampled_access;
  covergroup transactions;
    option.per_instance=1;
    word_length: coverpoint sampled_word_length { bins eight_bits={64'h3}; }
    access: coverpoint sampled_access { bins writes={64'h1}; bins reads={64'h2}; }
    access_format: cross access, word_length;
  endgroup
  function new(string name,uvm_component parent); super.new(name,parent); transactions=new(); endfunction
  function void write(cg_item tr);
    if(!$cast(observed,tr.clone())) `uvm_fatal("COV_COPY", "transaction copy failed")
    if((observed.kind==1 || observed.kind==2) && observed.address==64'h3) begin
      sampled_word_length=(observed.data & 64'h3) >> 0;
      sampled_access=(observed.kind & 64'h3) >> 0;
      samples++; transactions.sample();
    end
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_info("PLAN_COVERAGE", $sformatf("line_format samples=%0d coverage=%0.2f", samples,transactions.get_inst_coverage()), UVM_LOW)
  endfunction
endclass
