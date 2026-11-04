# Code execution plan

Order: clock → reset → all interface bases → assess/build each interface → each feature → integration.

Each step: retrieve → understand_and_pseudocode → implement → validate → checkpoint. Compilation/simulation are deferred.

1. **Clock** — PASS, checkpoint
2. **Reset** — PASS, checkpoint
3. **Interrupt output interface** — PASS, checkpoint
4. **UART serial data interface** — PASS, checkpoint
5. **Modem control handshake interface** — PASS, checkpoint
6. **WISHBONE slave register access interface** — PASS, checkpoint
7. **Assess Interrupt output interface** — PASS, checkpoint
8. **Interrupt output interface collateral** — PASS, checkpoint
9. **Assess UART serial data interface** — PASS, checkpoint
10. **UART serial data interface collateral** — PASS, checkpoint
11. **Assess Modem control handshake interface** — PASS, checkpoint
12. **Modem control handshake interface collateral** — PASS, checkpoint
13. **Assess WISHBONE slave register access interface** — PASS, checkpoint
14. **WISHBONE slave register access interface collateral** — PASS, checkpoint
15. **Fixed-period clock stimulus** — PASS, checkpoint
16. **Chip reset bring-up sequence** — PASS, checkpoint
17. **Clock period coverage** — PASS, checkpoint
18. **Interrupt and baud passive monitors** — PASS, checkpoint
19. **WISHBONE slave monitor** — PASS, checkpoint
20. **Interrupt ID coverage** — DEFERRED, checkpoint
21. **Reset-state scoreboard** — PASS, checkpoint
22. **WISHBONE init config sequence** — PASS, checkpoint
23. **WISHBONE register coverage** — PASS, checkpoint
24. **WISHBONE agent scoreboard** — DEFERRED, checkpoint
25. **X/Z protocol check** — PASS, checkpoint
26. **Divisor latch coverage** — PASS, checkpoint
27. **DLAB gating check** — PASS, checkpoint
28. **Normal and loopback traffic sequences** — PASS, checkpoint
29. **UART serial data monitor** — PASS, checkpoint
30. **WISHBONE top stimulus** — DEFERRED, checkpoint
31. **Address by DLAB cross** — DEFERRED, checkpoint
32. **End-to-end and architecture scoreboard** — PASS, checkpoint
33. **IER enable and IIR pending** — PASS, checkpoint
34. **Line-status and error cross** — DEFERRED, checkpoint
35. **LSR status and clear** — DEFERRED, checkpoint
36. **Modem-status interrupt** — PASS, checkpoint
37. **Top virtual and normal traffic control** — DEFERRED, checkpoint
38. **IIR priority and fixed bits** — DEFERRED, checkpoint
39. **Interrupt and line-error checks** — DEFERRED, checkpoint
40. **Modem by traffic cross** — PASS, checkpoint
