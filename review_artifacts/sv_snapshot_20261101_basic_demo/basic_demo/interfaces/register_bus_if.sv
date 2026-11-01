// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
interface register_bus_if(input logic clk, input logic reset);
  logic [2:0] addr;
  logic [7:0] wdata;
  logic [7:0] rdata;
  logic [0:0] we;
  logic [0:0] stb;
  logic [0:0] cyc;
  logic [0:0] ack;
  logic [0:0] sel;
endinterface
