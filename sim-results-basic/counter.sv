// Basic smoke testbench: 4-bit counter, three posedge samples.
module counter_tb;
  logic clk = 0, rst = 1;
  logic [3:0] count;
  always #5 clk = ~clk;
  always_ff @(posedge clk) count <= rst ? '0 : count + 1;
  initial begin
    #12 rst = 0;
    repeat (3) @(posedge clk) $display("t=%0t count=%0d", $time, count);
    $finish;
  end
endmodule
