# e2e-sim: ephemeral E2E xezim sim nodes

Run xezim simulations on a big E2E cloud node, then stop paying for it.
Default end state is **pause** (`power_off`: compute billing stops, disk and
the built xezim binary persist); `kill` deletes the node entirely.

Cheapest shape by construction: hourly on-demand nodes with **no** backup,
encryption, BitNinja, reserved IP, snapshot, or extra-volume code paths.
The tool cannot enable them.

## Cost (public rate card, USD/hr ex-taxes, Oct 2026)

| Plan | vCPU | RAM | $/hr | Notes |
|---|---|---|---|---|
| C3.16GB | 8 | 16 GB | 0.096 | cheapest big-enough |
| **C3.32GB (default)** | **16** | **32 GB** | **0.194** | SoC headroom |
| C3.64GB | 20 | 64 GB | 0.386 | largest usual |
| M3.32GB | 4 | 32 GB | 0.08 | only if RAM-bound, not CPU-bound |

C3 (compute-optimized, NVMe, bundled disk) beats E1 at these sizes
(E1LC-16.48GB is $0.354/hr *plus* separately-billed disk). xezim sims are
CPU-bound (C906 SoC peaks well under 1 GiB), so C3 is the value pick; take
M3 only when the run is RAM-bound.

A 2-hour C3.32GB run costs about $0.39. First boot also builds xezim once
(~15-25 min, inside the same billed hour); every later run reuses the
paused node and the ready binary. Verify the first bill with
`e2e-sim status --billing`.

## Billing granularity: hours, not minutes

MyAccount CPU billing is **hourly** (E2E docs: "all services are billed
hourly"; "as soon as an hour finishes, the relevant amount is deducted").
Per-minute granularity applies to **GPU resources only**. Practical rules:

- 1 minute of use in an hour bills the **full hour** ($0.194 on C3.32GB).
  E2E does not document partial-hour rounding, so assume any Running time
  in a clock hour bills that hour; confirm on the first invoice.
- 5 min on, 5 min off, 5 min on inside one clock hour bills **1 hour**;
  straddling an hour boundary bills **2**. Batch short runs: use `--keep`
  for a burst of commands, then one `e2e-sim pause` at the end.
- Pausing immediately still wins big: it caps each session at ~1 hour
  instead of 24 h/day. One sim a day for a month is ~30 x $0.194 = $5.82
  with immediate pause vs ~$141 always-on.
- Installing xezim also needs the node Running, so the one-time build
  (~15-25 min) costs part of one billed hour. After that the binary
  survives on the paused disk. Skip the build entirely with
  `--xezim-bin ./target/release/xezim` (uploads a local Linux x86_64
  build instead).

## Setup (once)

1. Create an API token in MyAccount > API & IAM; note the project id.
2. Have an SSH key pair (`~/.ssh/id_ed25519`).
3. Copy `.env.example` to `.env` (git-ignored) and fill in:
   `E2E_AUTH_TOKEN`, `E2E_API_KEY` (if issued), `E2E_PROJECT_ID`.
   Region defaults are Chennai / `chennai`.
4. Make sure the project's default security group allows inbound SSH
   (port 22), or the run will fail at the SSH-wait step.
5. Discover the exact plan/image SKUs (never hardcode them):

```bash
.venv/bin/e2e-sim discover --write-config e2e-sim-config.json
```

`E2E_PLAN` is the **exact catalog SKU** for the node size, e.g.
`C3-16vCPU-32RAM-200DISK-C3-Onetemplate-Ubuntu24.04-Chennai` — not the
display name (`C3.32GB`). `E2E_IMAGE` is likewise exact (e.g.
`Ubuntu-24.04-Distro`). Both vary by region and change over time, so
`discover` reads them live from the catalog and writes the config file;
leave them empty until then.

## Usage

```bash
# full flow: create/resume -> xezim ready -> upload -> simulate ->
# fetch results -> pause (compute billing stops)
# NOTE: --config/--workdir/--node-id come BEFORE the subcommand.
.venv/bin/e2e-sim --config e2e-sim-config.json run --src ./uart_tb \
  --results sim-results -- top.sv tb.sv +UVM_TESTNAME=my_test

# variants
.venv/bin/e2e-sim run ... --kill        # delete instead of pause (zero everything)
.venv/bin/e2e-sim run ... --keep        # leave running (keeps billing!)
.venv/bin/e2e-sim run ... --xezim-bin ./target/release/xezim  # skip node build

# any command, same lifecycle (e2e-exec is e2e-sim exec as its own binary)
.venv/bin/e2e-exec --config e2e-sim-config.json -- nproc
.venv/bin/e2e-exec --src ./uart_tb --results sim-results -- \
  /opt/xezim-sim/xezim-bin top.sv tb.sv
.venv/bin/e2e-exec --keep -- make -C work regress   # burst mode, pause after

# lifecycle
.venv/bin/e2e-sim up --build            # create/resume without simulating
.venv/bin/e2e-sim pause                 # power off: no compute billing
.venv/bin/e2e-sim resume                # power back on (~1 min, xezim ready)
.venv/bin/e2e-sim status --billing      # state + spend check
.venv/bin/e2e-sim kill --yes            # irreversible delete
.venv/bin/e2e-sim ssh -- tail -f /opt/xezim-sim/build.log
```

Node state lives in `.e2e-sim-state.json` in the working directory
(git-ignored). Use `--workdir` to keep one state per project.

## How pause saves money

| State | Compute $/hr | Data | Next run |
|---|---|---|---|
| Running | full plan rate | live | immediate |
| Paused (`power_off`) | **0** (storage only, bundled disk) | persists, xezim stays built | ~1 min resume |
| Killed (deleted) | 0, nothing left | gone | full re-provision + rebuild |

If a step fails mid-run the node is deliberately left as-is so results can
be recovered; the error message says to `pause` or `kill` explicitly.
Deleting a node releases its auto-allocated public IP; this tool never
creates reserved IPs or volumes, so there is nothing else to release.

## API surface used (MyAccount REST, `.../myaccount/api/v1`)

Bearer auth, `project_id`/`location` query params. Endpoints: `GET
/images/os-category/`, `GET /images/` (catalog), `POST /nodes/` (hourly
on-demand create), `GET /nodes/{id}/`, `PUT /nodes/{id}/actions/`
(`power_off`/`power_on`), `DELETE /nodes/{id}/`,
`GET /nodes/nodebillinglog/{vm_id}`. See `src/e2e_sim/client.py`.

Live notes (verified 2026-10-29 on node 352624, Chennai C3.32GB):
`E2E_PROJECT_ID` is optional — omit it to use the default project (a wrong
id fails with a misleading 401 "suspended due to payment"). SSH user is
`root`, not `ubuntu`. `start_scripts` do not reliably execute (image has
no cloud-init), so `ensure_xezim` (re)starts the build over SSH when the
marker is absent. `--node-id` seeds an empty state file on
`up`/`run`/`exec`. Full live sim run + pause: see session log.
