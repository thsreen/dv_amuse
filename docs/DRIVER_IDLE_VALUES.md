# Driver idle settings and tie-offs

An active agent owns its DUT input pins. `Agent.idle_values` maps **physical RTL input names** to
integer default settings. Generated drivers expose `virtual function void drive_reset_values()` and
call it at startup. This is the single place that initializes every owned input through its own virtual
interface; there are no separate idle assignments, continuous assignments or additional drivers.
Generic inputs default to zero; supported protocol backends retain their existing defaults (such as
serial receive high). Approved settings override those defaults inside the same function, and must fit the pin width,
belong to that active agent, and match backend capability. The built-in serial backend supports
idle-high receive input; WISHBONE control pins idle low. Custom drivers must preserve their declared
idle behavior when implementing transaction hooks.

The generic driver exposes a separate `drive_item()` task for the drive hook. Both driver and monitor
have the full interface through their VIF. The generic monitor keeps typed local samples of every
signal, clears them in `reset_values()`, samples them in `sample_signals()`, and runs its separate
`monitor_interface()` observation hook. Monitor reset clears local state only; it never drives DUT
outputs. The generic monitor samples at the interface clock and clears samples while reset is active;
protocol-specific hooks may implement their documented observation timing. Driver reset initialization
is a reusable callable function; interruption of an in-flight transaction by asynchronous reset is
not added by this scaffold.

Defaults are testbench pin initialization, not inferred DUT register reset contents. Clock/reset
ports remain owned by their common UVCs. The standalone `uvm_agent` driver template likewise exposes
`drive_reset_values()` for controllable DUT inputs before its drive loop.

`tie_offs` represents permanent driving of inputs with no agent owner. A pin cannot simultaneously
belong to an active agent and a tie-off. These ownership checks remain enabled in quick testing.

Infrastructure reviews expose `idle_values` separately. For active-agent interfaces they request
roles and idle values, excluding tie-offs. An older tie-off approval that conflicts with an active
agent causes a replacement review. The old receipt stays in history; after the new idle decision is
approved, the overlapping tie-off is superseded in the effective bindings. Human confirmation or
explicit isolated quick-testing inference is still required; no silent reinterpretation occurs.

Recorded approval settings are applied to the generated agent and revalidated before rendering.
Source labels remain human-approved or test-only as appropriate. Restart the orchestrator before
retrying `/code` so the new review fields and contract are loaded.
