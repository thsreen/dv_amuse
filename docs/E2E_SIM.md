# e2e-sim (submodule)

The ephemeral-E2E-node tool now lives in its own repository,
[thsreen/e2e-sim](https://github.com/thsreen/e2e-sim), checked out as the
`tools/e2e_sim` submodule. Full docs are in its `README.md`.

```bash
# first clone / after submodule changes
git submodule update --init tools/e2e_sim

# run from this directory (reads dv_agent/.env, state and config here)
export PYTHONPATH=tools/e2e_sim/src
.venv/bin/python -m e2e_sim --config e2e-sim-config.json run --src ./tb \
  --results sim-results -- top.sv tb.sv
.venv/bin/python -m e2e_sim --node-id 352624 status --billing
```

`e2e-exec` equivalent without installing:
`PYTHONPATH=tools/e2e_sim/src .venv/bin/python -c
"from e2e_sim.cli import exec_main; raise SystemExit(exec_main())" -- <cmd>`.
Or `pip install -e tools/e2e_sim` for real `e2e-sim` / `e2e-exec` commands.
