"""Flow definition loading, validation and argument resolution.

A flow JSON file is the orchestrator's contract: the recommended step order,
the execution budgets, and the strict never-do list. Anything the file does
not allow is refused; anything it forbids is blocked even if the model asks.
"""
import json
import re
from pathlib import Path

FLOW_SCHEMA_VERSION = 1

# The strict never-do list must always contain this rule: implementation
# detail from RTL must never flow directly into generated verification code.
REQUIRED_FORBIDDEN = ("NO_RTL_INTO_UVM",)

AGENTS = ("dv", "rtl")
STEP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
FULL_PLACEHOLDER_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}$")

DEFAULT_POLICY = dict(max_attempts_per_step=2, max_revisits_per_step=1,
                      max_overrides=3, max_total_tool_calls=32,
                      default_step_timeout_s=600, global_timeout_s=3600,
                      max_extra_prompt_chars=2000)


class FlowError(ValueError):
    pass


def load_flow(path: Path) -> dict:
    try:
        flow = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise FlowError(f"cannot read flow file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FlowError(f"flow file {path} is not valid JSON: {exc}") from exc
    if not isinstance(flow, dict):
        raise FlowError(f"flow file {path} must contain a JSON object")
    return validate_flow(flow)


def validate_flow(flow: dict) -> dict:
    """Check the flow contract and return it with defaults filled in."""
    errors: list[str] = []
    if flow.get("version") != FLOW_SCHEMA_VERSION:
        errors.append(f"version must be {FLOW_SCHEMA_VERSION}")
    if not isinstance(flow.get("name"), str) or not flow["name"].strip():
        errors.append("name must be a non-empty string")
    steps = flow.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps must be a non-empty list")
        steps = []
    seen: set[str] = set()
    for i, step in enumerate(steps):
        where = f"steps[{i}]"
        if not isinstance(step, dict):
            errors.append(f"{where} must be an object")
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not STEP_ID_RE.match(sid):
            errors.append(f"{where}.id must match {STEP_ID_RE.pattern}")
        elif sid in seen:
            errors.append(f"{where}.id duplicates {sid!r}")
        else:
            seen.add(sid)
        if not isinstance(step.get("tool"), str) or not step["tool"].strip():
            errors.append(f"{where}.tool must be a non-empty string")
        if step.get("agent") not in AGENTS:
            errors.append(f"{where}.agent must be one of {AGENTS}")
        args = step.get("args", {})
        if not isinstance(args, dict):
            errors.append(f"{where}.args must be an object")
        for key in ("optional", "review_gate", "allow_extra_prompt"):
            if key in step and not isinstance(step[key], bool):
                errors.append(f"{where}.{key} must be a boolean")
        for key in ("timeout_s", "max_attempts"):
            if key in step and (not isinstance(step[key], int) or step[key] <= 0):
                errors.append(f"{where}.{key} must be a positive integer")
    forbidden = flow.get("forbidden")
    if not isinstance(forbidden, list) or not forbidden:
        errors.append("forbidden must be a non-empty list of never-do rules")
        forbidden = []
    rule_ids: set[str] = set()
    for i, rule in enumerate(forbidden):
        where = f"forbidden[{i}]"
        if not isinstance(rule, dict):
            errors.append(f"{where} must be an object")
            continue
        rid = rule.get("id")
        if not isinstance(rid, str) or not rid.strip():
            errors.append(f"{where}.id must be a non-empty string")
        elif rid in rule_ids:
            errors.append(f"{where}.id duplicates {rid!r}")
        else:
            rule_ids.add(rid)
        if not isinstance(rule.get("title"), str) or not rule["title"].strip():
            errors.append(f"{where}.title must be a non-empty string")
    for required in REQUIRED_FORBIDDEN:
        if required not in rule_ids:
            errors.append(f"forbidden must include the strict rule {required!r}")
    policy = flow.get("policy", {})
    if not isinstance(policy, dict):
        errors.append("policy must be an object")
        policy = {}
    for key, default in DEFAULT_POLICY.items():
        value = policy.get(key, default)
        if not isinstance(value, int) or value < 0:
            errors.append(f"policy.{key} must be a non-negative integer")
        elif key in ("max_total_tool_calls", "default_step_timeout_s",
                     "global_timeout_s", "max_extra_prompt_chars") and value <= 0:
            errors.append(f"policy.{key} must be positive")
        elif key == "max_attempts_per_step" and value < 1:
            errors.append("policy.max_attempts_per_step must be at least 1")
    if errors:
        raise FlowError("invalid flow: " + "; ".join(errors))
    normalized = dict(flow)
    normalized["policy"] = {k: policy.get(k, v) for k, v in DEFAULT_POLICY.items()}
    normalized_steps = []
    for step in steps:
        item = dict(step)
        item.setdefault("args", {})
        item.setdefault("optional", False)
        item.setdefault("review_gate", False)
        item.setdefault("allow_extra_prompt", True)
        item.setdefault("timeout_s", normalized["policy"]["default_step_timeout_s"])
        item.setdefault("max_attempts", normalized["policy"]["max_attempts_per_step"])
        normalized_steps.append(item)
    normalized["steps"] = normalized_steps
    return normalized


def _resolve_value(value, variables: dict, step_id: str):
    if isinstance(value, str):
        full = FULL_PLACEHOLDER_RE.match(value.strip())
        if full:
            name, default = full.group(1), full.group(2)
            if name not in variables:
                if default is not None:
                    return default
                raise FlowError(f"step {step_id!r} needs variable {name!r}, "
                                f"which no --var/--option supplied")
            return variables[name]
        def replace(match: re.Match) -> str:
            name, default = match.group(1), match.group(2)
            if name not in variables:
                if default is not None:
                    return default
                raise FlowError(f"step {step_id!r} needs variable {name!r}, "
                                f"which no --var/--option supplied")
            item = variables[name]
            if isinstance(item, (dict, list)):
                raise FlowError(f"variable {name!r} cannot be embedded in a string")
            return str(item)
        return PLACEHOLDER_RE.sub(replace, value)
    if isinstance(value, list):
        return [_resolve_value(v, variables, step_id) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_value(v, variables, step_id) for k, v in value.items()}
    return value


def resolve_args(args: dict, variables: dict, step_id: str) -> dict:
    """Substitute ${name} (or ${name:-default}) placeholders.

    A sole placeholder keeps its type, so lists survive; embedded ones become
    strings. A missing variable without a default is a FlowError naming the
    variable and the step."""
    return {k: _resolve_value(v, variables, step_id) for k, v in args.items()}
