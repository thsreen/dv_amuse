# Common register write

Any generated sequence can write a declared register by name. The call does not know the bus address, the bus
agent or its sequencer.

```systemverilog
cg_reg_access::write(this, "line_control", 8'h83);          // name, value
cg_reg_access::write(this, "fifo_control", 6, 4);           // optional: 4 idle bus cycles after the transfer
cg_reg_access::write_all(this, '{"divisor_high","divisor_low"}, '{0, 2});   // several, in order
```

In the code contract the same thing is an operation: `{"kind": "register_write", "register_id": "line_control", "data": 131}`
(optional `count` and `cycles`; `data` and `cycles` can be bound to sequencer variables like any operation).

## What is generated (`templates/codegen/reg_access.svh.tmpl` -> `uvm/cg_reg_access.svh`)

| Class | Role |
|---|---|
| `cg_reg_info` | one register: id, owning agent, address, width, access, mask, reset |
| `cg_reg_map` | shared map filled from the contract's `registers`; `bind_sequencer(agent, sqr)`; `lookup(name)` lists the declared names when one is unknown |
| `cg_reg_write_seq` | the sequence: fields `reg_name`, `value`, `gap_cycles`; refuses a read-only register and a value wider than the register |
| `cg_reg_access` | static `write` and `write_all`; starts the sequence on the owning agent's sequencer as a child of the caller |

The file is included right after `cg_item` and before every sequence, and only when the contract declares registers.
Each test binds the sequencer of every active agent that owns a register before it starts, so a sequence running on
one agent (for example the serial agent) can still write a register that lives on the bus agent.

## Checked before rendering (`codegen/validate.py`)

The register must be declared (the message lists the valid ids), must not be read-only, the value must fit its width,
and the owning agent must be active. Only `register_write` operations may set `register_id`.

## Limits

- Write only. A read, poll or read-modify-write helper is the natural next step and would reuse the same map.
- The write is a plain bus write of the whole value; the register `mask` is carried on the item for the scoreboard.
- Two sequences in one concurrent test stage that both end up on the same bus are serialised by the sequencer, but the
  existing rule against racing sequences of the same agent in one stage still applies to their own agents.

Verified with a real Xezim + UVM run on the UART fixture: its initialization sequence uses only named register
writes, a sequence on the serial agent writes a bus register, and both tests pass with the same scoreboard
comparisons (3 and 4) as the raw-write version
(`DV_AGENT_TEST_SIMULATION=1 pytest tests/test_register_write.py -k real_uart`).
