interface modem_control_if_if(input logic clk, input logic reset);
  logic [0:0] rts_pad_o;
  logic [0:0] dtr_pad_o;
  logic [0:0] cts_pad_i;
  logic [0:0] dsr_pad_i;
  logic [0:0] ri_pad_i;
  logic [0:0] dcd_pad_i;
endinterface
