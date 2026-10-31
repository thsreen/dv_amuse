"""Deterministic role of an interface group, so prompts and checks treat a clock differently from a bus.

The verification plan used to ask for the same workup on every group: a correctness mechanism per agent,
scoreboards over every agent. A clock or reset that the testbench supplies has no behaviour to compare, so
that request produced self-checks and scoreboards for a clock source. The role is computed from the
verified group (category and signal directions), never by the model.

- infrastructure_source: clock or reset group whose signals are all DUT inputs. The testbench supplies it.
- observed_output: group whose signals are all DUT outputs (interrupts, status, derived clocks). Monitored only.
- functional_interface: everything else (buses, data and flow-control groups, anything with inputs and outputs).
"""

INFRASTRUCTURE = "infrastructure_source"
OBSERVED_OUTPUT = "observed_output"
FUNCTIONAL = "functional_interface"
INFRASTRUCTURE_CATEGORIES = ("clock", "reset")


def group_role(group: dict) -> str:
    directions = {s.get("direction") for s in group.get("signals", [])}
    only_inputs = directions == {"input"}
    only_outputs = directions == {"output"}
    if group.get("category") in INFRASTRUCTURE_CATEGORIES and only_inputs:
        return INFRASTRUCTURE
    if only_outputs:
        return OBSERVED_OUTPUT  # includes a derived clock: category "clock", but the DUT drives it
    return FUNCTIONAL


def group_roles(groups: list[dict]) -> dict[str, str]:
    return {g["name"]: group_role(g) for g in groups}
