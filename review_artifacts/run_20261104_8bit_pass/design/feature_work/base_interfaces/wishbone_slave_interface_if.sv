interface wishbone_slave_interface_base_if(input logic clk, input logic reset);
  logic [2:0] wb_adr_i;
  logic [3:0] wb_sel_i;
  logic [7:0] wb_dat_i;
  logic [7:0] wb_dat_o;
  logic [0:0] wb_we_i;
  logic [0:0] wb_stb_i;
  logic [0:0] wb_cyc_i;
  logic [0:0] wb_ack_o;
endinterface
