# UVM agent template v1

`template.json` lists every generated component, output file, purpose and
editable slot. Each `*.tmpl` file defines one interface, package or class.
The script owns all standard UVM plumbing and substitutes common identifiers
such as `{{UVC_NAME}}`, `{{CLOCK_SIGNAL}}`, fields, assignments and includes.
Generated files carry the `uvm_agent_v1` identifier.

Pass an optional JSON argument file to `build-uvm --agent-args`:

```json
{
  "template_id": "uvm_agent_v1",
  "name": "my_block",
  "custom": {
    "driver.declarations": "int unsigned driven_items;",
    "driver.drive": "driven_items++;",
    "scoreboard.check": "// Add a reviewed predictor and comparisons here."
  },
  "sequences": {
    "A sequence name from the plan": {
      "configure": "tr.valid = 1'b1;"
    }
  },
  "cited_chunk_ids": ["a test-plan chunk ID"]
}
```

`name` is a simple rename. Custom snippets may use `{{UVC_NAME}}`,
`{{CLOCK_SIGNAL}}` and, when bound, `{{RESET_SIGNAL}}`; named sequence snippets
may also use `{{SEQUENCE_ID}}`. The script substitutes only these identifiers.
`custom` and per-sequence `configure` are code
insertions in the named slots. `imports` may list additional package names.
The script rejects unknown slots, unknown sequence names, class/package
declarations inside snippets, and oversized input. These checks are structural,
not a SystemVerilog compiler or proof of expected behavior. The output stays
`NEEDS_REVIEW`, and the manifest records the template hash, filled slot names,
citations and a custom-code hash.

A later LLM can read the copied `uvm_agent_template/` directory in a generated
repository and return this JSON shape. It should draw behavior only from the
verification test plan. Script-generated signal fields, standard UVM classes,
connections and package includes stay deterministic.
