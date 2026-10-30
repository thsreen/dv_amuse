"""Hard enforcement for the flow's strict never-do list.

Every rule below fails closed: an unknown rule ID in the flow, or any match
on a known rule, blocks the proposed tool call or model override and sends
the run back to the owner. Guards never call the model.
"""
import json
from pathlib import Path

# Rule ID -> short title. The flow JSON carries the full descriptions; this
# table decides which IDs the engine knows how to enforce.
KNOWN_FORBIDDEN = {
    "NO_RTL_INTO_UVM": "no RTL behaviour/excerpts directly into verification code",
    "NO_RTL_AS_SPEC_AUTHORITY": "RTL observations stay INFERRED and NEEDS_REVIEW",
    "NO_DESIGN_MUTATION": "tools write only under the orchestrator output directory",
    "NO_SPEC_FLOW_CONTAMINATION": "spec steps take no RTL input except the opt-in plan section",
    "NO_NEW_TOOLS": "the model uses only steps and tools named in the flow",
    "NO_MANDATORY_SKIP": "the model skips only steps marked optional",
}

# Tools that implement the specification-only flow. Only dv_testplan may take
# an explicit rtl_graph (the opt-in observations section, D-032).
SPEC_ONLY_TOOLS = frozenset({"dv_ingest", "dv_build_graph", "dv_interfaces",
                             "dv_registers", "dv_strategy"})

# Argument keys that would carry RTL behaviour into a tool call.
RTL_ARG_KEYS = frozenset({"rtl_graph", "rtl_excerpts", "rtl_evidence",
                          "rtl_facts", "rtl_context", "rtl_scope"})

# Markers a follow-up prompt must not use to smuggle RTL excerpts into UVM.
RTL_PROMPT_MARKERS = ("RTL_EXCERPT", "[RTL]")

# Output keys that may legitimately point at existing files.
OUT_ARG_KEYS = ("out", "dv_out", "rtl_out", "uvm_out")


def unknown_rules(rule_ids) -> list[str]:
    return [rid for rid in rule_ids if rid not in KNOWN_FORBIDDEN]


def _non_empty(args: dict, keys: frozenset) -> list[str]:
    return sorted(k for k in keys if args.get(k) not in (None, "", [], {}))


def pre_tool_check(*, tool: str, args: dict, extra_prompt: str,
                   out_dir: Path, rtl_behavior_files: set[str]) -> list[str]:
    """Violations that forbid this tool call. Empty means allowed."""
    violations: list[str] = []
    if tool == "uvm_build":
        bad_keys = _non_empty(args, RTL_ARG_KEYS)
        if bad_keys:
            violations.append(
                f"NO_RTL_INTO_UVM: uvm_build must not take RTL inputs "
                f"({', '.join(bad_keys)}); only the built interface JSON, "
                f"the test plan and reviewed agent arguments are allowed")
        for key in ("interface", "testplan", "agent_args"):
            candidate = args.get(key)
            if isinstance(candidate, str) and candidate:
                try:
                    resolved = str(Path(candidate).resolve())
                except OSError:
                    resolved = candidate
                if resolved in rtl_behavior_files:
                    violations.append(
                        f"NO_RTL_INTO_UVM: uvm_build {key} points at RTL behaviour "
                        f"output ({candidate})")
        upper = (extra_prompt or "").upper()
        if any(marker in upper for marker in RTL_PROMPT_MARKERS):
            violations.append("NO_RTL_INTO_UVM: follow-up prompt for uvm_build "
                              "must not carry RTL excerpts")
    if tool in SPEC_ONLY_TOOLS:
        bad_keys = _non_empty(args, RTL_ARG_KEYS)
        if bad_keys:
            violations.append(
                f"NO_SPEC_FLOW_CONTAMINATION: {tool} is specification-only and "
                f"must not take {', '.join(bad_keys)}")
    for key in OUT_ARG_KEYS:
        candidate = args.get(key)
        if isinstance(candidate, str) and candidate:
            try:
                inside = Path(candidate).resolve().is_relative_to(out_dir.resolve())
            except OSError:
                inside = False
            if not inside:
                violations.append(
                    f"NO_DESIGN_MUTATION: {tool} {key} ({candidate}) is outside "
                    f"the orchestrator output directory ({out_dir})")
    upper = (extra_prompt or "").upper()
    if tool == "dv_testplan" and "RTL" in upper and "APPROV" in upper:
        violations.append("NO_RTL_AS_SPEC_AUTHORITY: a follow-up prompt must not "
                          "approve RTL observations; they stay NEEDS_REVIEW for "
                          "the RTL design engineer")
    return violations


def post_testplan_check(*, doc_path: Path, rtl_used: bool,
                        expected_authority: str | None = None) -> list[str]:
    """After a passing plan step, prevent RTL evidence from gaining spec authority."""
    if not rtl_used and not expected_authority:
        return []
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["NO_RTL_AS_SPEC_AUTHORITY: cannot verify the RTL observations "
                f"section in {doc_path}; refusing to treat it as reviewed"]
    violations: list[str] = []
    if expected_authority == "RTL_INFERRED":
        if doc.get("source_authority") != "RTL_INFERRED":
            violations.append("NO_RTL_AS_SPEC_AUTHORITY: RTL-derived plan lost its inferred source authority")
        def check(value):
            if isinstance(value, list):
                for item in value:
                    check(item)
            elif isinstance(value, dict):
                if value.get("provenance") == "DOCUMENTED":
                    violations.append("NO_RTL_AS_SPEC_AUTHORITY: RTL-derived plan contains DOCUMENTED provenance")
                for item in value.values():
                    check(item)
        check(doc.get("sections", []))
        check(doc.get("registers"))
        check(doc.get("interfaces"))
    for section in doc.get("sections", []):
        if section.get("generator") != "rtl_observations":
            continue
        for entry in section.get("entries", []):
            if entry.get("review_status") != "NEEDS_REVIEW":
                violations.append(
                    "NO_RTL_AS_SPEC_AUTHORITY: RTL observation "
                    f"{entry.get('id', '?')} must stay NEEDS_REVIEW")
            if entry.get("provenance") == "DOCUMENTED":
                violations.append(
                    "NO_RTL_AS_SPEC_AUTHORITY: RTL observation "
                    f"{entry.get('id', '?')} must not be DOCUMENTED")
    return violations
