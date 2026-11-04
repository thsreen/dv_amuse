#!/bin/sh
# Compile and run the script-chosen test from this folder. Requires Xezim 0.11.3, an Accellera UVM 2020.3.1 source tree and the UART16550 RTL.
# Usage: XEZIM=/path/xezim UVM_SRC=/path/uvm/src UART_RTL=/path/uart16550/rtl/verilog sh reproduce.sh
set -eu
HERE=$(cd "$(dirname "$0")" && pwd); TB="$HERE/testbench"; OUT=$(mktemp -d); cd "$OUT"
"$XEZIM" --simulate --error-exit --fst "$OUT/quick_basic.fst" -s verification_top \
  -I "$TB" -I "$TB/common_uvc/clock" -I "$TB/common_uvc/reset" -I "$TB/common_uvc/common" -I "$UVM_SRC" -I "$UART_RTL" \
  -D UVM_NO_DPI -D UVM_REPORT_DISABLE_FILE_LINE -D DATA_BUS_WIDTH_8 \
  "$UVM_SRC/uvm_pkg.sv" \
  "$UART_RTL/raminfr.v" \
  "$UART_RTL/uart_debug_if.v" \
  "$UART_RTL/uart_receiver.v" \
  "$UART_RTL/uart_regs.v" \
  "$UART_RTL/uart_rfifo.v" \
  "$UART_RTL/uart_sync_flops.v" \
  "$UART_RTL/uart_tfifo.v" \
  "$UART_RTL/uart_top.v" \
  "$UART_RTL/uart_transmitter.v" \
  "$UART_RTL/uart_wb.v" \
  "$TB/common_uvc/clock/clock_if.sv" \
  "$TB/common_uvc/reset/reset_if.sv" \
  "$TB/common_uvc/clock/clock_pkg.sv" \
  "$TB/common_uvc/reset/reset_pkg.sv" \
  "$TB/common_uvc/common/common_pkg.sv" \
  "$TB/interfaces/interrupt_output_if.sv" \
  "$TB/interfaces/uart_serial_data_if.sv" \
  "$TB/interfaces/modem_control_if_if.sv" \
  "$TB/interfaces/wishbone_slave_interface_if.sv" \
  "$TB/uart_top_verification_pkg.sv" \
  "$TB/checks/wishbone_slave_interface_assertions.sv" \
  "$TB/verification_top.sv" \
  +UVM_TESTNAME=quick_basic +seed=1 > "$OUT/simulation.log" 2>&1
grep -E 'SCOREBOARD_SUMMARY\]|^UVM_ERROR :|^UVM_FATAL :|FUNCTIONAL_TEST_PASS' "$OUT/simulation.log"
echo "Log and waveform: $OUT"
