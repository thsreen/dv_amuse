// QUICK TESTING ONLY: inferred auto approvals are not human approval or design sign-off.
interface modem_control_if_if(input logic clk, input logic reset);
  logic [0:0] RTS_PAD_O;
  logic [0:0] DTR_PAD_O;
  logic [0:0] CTS_PAD_I;
  logic [0:0] DSR_PAD_I;
  logic [0:0] RI_PAD_I;
  logic [0:0] DCD_PAD_I;
endinterface
