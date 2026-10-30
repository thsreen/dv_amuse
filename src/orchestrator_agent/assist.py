"""Terminal assistant: adjacent asks outside the four commands.

Free text that is not a repository description is routed here first. Every
intent is deterministic and offline except rerun, which executes one registry
tool through runner.run_single_tool (guards enforced, never-do list intact).
Readers only read inside the run directory or user-named files; nothing here
executes a shell, touches design sources, or invents tools.
"""
import json
import re
from pathlib import Path

# Whole-line fresh phrases. Tight on purpose: anything longer (a repo path or
# a requirement sentence) falls through to the normal scan path.
FRESH_RE = re.compile(
    r"(?:please\s+)?(?:start\s+(?:over|fresh|again)|be\s+fresh|go\s+fresh|"
    r"fresh\s+start|reset(?:\s+session)?)\s*\.?\s*$", re.I)

EXPLAIN_RE = re.compile(
    r"\bwhy\b.*\b(fail\w*|block\w*|errors?|wrong|stuck)|\bwhy\b\s*\??\s*$|"
    r"what\s+went\s+wrong|\bwhat\b.*\b(fail\w*|errors?)\b|"
    r"\bexplain\b|\bshow\b.*\breview\b|"
    r"(?:\bshow\b|\bexplain\b|\bwhat\b|\bwhy\b).*\breview\b", re.I)
STATUS_RE = re.compile(r"^\s*status(?:\s+of\s+(?P<path>.+?))?\s*\.?\s*$", re.I)
VALIDATE_HEAD_RE = re.compile(r"^\s*(?:validate|check\s+flow)\b\s*(?P<rest>.*?)\s*\.?\s*$", re.I)
HELP_RE = re.compile(r"^\s*help\s*\??\s*$", re.I)
RERUN_RE = re.compile(
    r"(?:\brerun\b|\brun\b|\bredo\b|\bregenerate\b)\s+(?P<target>[a-z_][a-z0-9_\- ]*)",
    re.I)
SHOW_RE = re.compile(
    r"(?:\bshow\b\s+|\blist\b\s+|\bwhat\b(?:\s+\w+){0,3}?\s+(?:are|is)\s+(?:the\s+)?)"
    r"(?P<target>[a-z_][a-z0-9_\- ]*)", re.I)

# Filler words skipped around a rerun/show target.
_FILLER = frozenset({"the", "a", "my", "me", "step", "stage", "again", "please"})

SHOW_TARGETS = ("interfaces", "interface", "registers", "register", "regmap",
                "strategy", "testplan", "test-plan", "plan", "sections",
                "review", "status", "summary")

# Friendly rerun names -> registry tool. uvm_build stays behind /code, which
# applies the documented-only policy gate before any code is emitted.
RERUN_TOOLS = {
    "ingest": "dv_ingest", "spec_ingest": "dv_ingest",
    "graph": "dv_build_graph", "spec_graph": "dv_build_graph", "build-graph": "dv_build_graph",
    "interfaces": "dv_interfaces", "ports": "rtl_extract", "rtl_ports": "rtl_extract",
    "extract": "rtl_extract", "registers": "dv_registers", "regmap": "dv_registers",
    "strategy": "dv_strategy", "testplan": "dv_testplan", "plan": "dv_testplan",
    "rtl_graph": "rtl_build_graph", "rtl-graph": "rtl_build_graph",
}


BARE_RERUN_RE = re.compile(r"^\s*(?:rerun|run|redo|regenerate)\s*\.?\s*$", re.I)


def _content_words(target: str) -> list[str]:
    return [w for w in target.split() if w not in _FILLER]


def _looks_like_path(token: str) -> bool:
    return bool(token) and ("/" in token or token.startswith((".", "~"))
                            or token.endswith(".json") or Path(token).exists())


def interpret(line: str) -> dict | None:
    """Route free text to an assistant intent, or None for the scan path."""
    text = line.strip()
    if not text or text.startswith("/"):
        return None
    if FRESH_RE.match(text):
        return dict(intent="fresh")
    if HELP_RE.match(text):
        return dict(intent="help")
    if EXPLAIN_RE.search(text):
        return dict(intent="explain")
    match = STATUS_RE.match(text)
    if match:
        path = (match.group("path") or "").strip().rstrip(".")
        if not path or _looks_like_path(path):
            return dict(intent="status", path=path)
        return None
    match = VALIDATE_HEAD_RE.match(text)
    if match:
        rest = match.group("rest").strip()
        tokens = [t.strip("\"'`") for t in rest.split()]
        paths = [t for t in tokens if _looks_like_path(t)]
        return dict(intent="validate", path=paths[-1] if paths else "")
    if BARE_RERUN_RE.match(text):
        return dict(intent="rerun", target="")
    match = RERUN_RE.search(text)
    if match:
        target = (match.group("target") or "").strip().lower().rstrip(".")
        words = _content_words(target)
        return dict(intent="rerun", target=" ".join(words))
    match = SHOW_RE.search(text)
    if match:
        target = (match.group("target") or "").strip().lower().rstrip(".?!")
        words = _content_words(target)
        if words and words[0] in SHOW_TARGETS:
            return dict(intent="show", target=words[0])
    return None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def explain_run(out_dir: Path) -> list[str]:
    """Why the run needs review: reason, pending step, violations, step table."""
    from .runner import RESULT_FILE, REVIEW_FILE
    review = _read_json(out_dir / REVIEW_FILE)
    result = _read_json(out_dir / RESULT_FILE)
    if review is None and result is None:
        return ["No run here yet — /plan first, then ask me to explain."]
    lines = []
    status = (review or {}).get("status") or (result or {}).get("status", "?")
    lines.append(f"Run status: {status}")
    reason = (review or {}).get("reason") or (result or {}).get("reason", "")
    if reason:
        lines.append(f"Reason: {reason}")
    pending = (review or {}).get("pending_step")
    if pending:
        lines.append(f"Pending step: {pending}")
    for violation in (review or {}).get("violations", [])[:5]:
        lines.append(f"Blocked by rule: {violation}")
    steps = (result or {}).get("steps", [])
    if steps:
        lines.append("Steps:")
        lines += [f"  {s.get('id')}: {s.get('status')} — {s.get('summary', '')}"[:160]
                  for s in steps[:12]]
    question = (review or {}).get("question", "")
    if question:
        lines.append(f"Owner action: {question}")
    return lines


def status_text(out_dir: Path) -> list[str]:
    """One-screen status of this run directory (or a named one)."""
    from .runner import RESULT_FILE, REVIEW_FILE
    result = _read_json(out_dir / RESULT_FILE)
    if result is None:
        return [f"no orchestrator result in {out_dir}"]
    lines = [f"Run: {result.get('status')} — {result.get('reason', '')}",
             f"Flow: {result.get('flow', '?')}",
             f"Tool calls: {result.get('tool_calls', 0)} "
             f"(overrides used: {result.get('overrides_used', 0)})"]
    for step in result.get("steps", [])[:12]:
        lines.append(f"  {step.get('id')}: {step.get('status')}")
    review = _read_json(out_dir / REVIEW_FILE)
    if review is not None:
        lines.append(f"Review: {review.get('status')} — {review.get('reason', '')}")
    return lines


def validate_text(flow_path: str) -> list[str]:
    """Validate a flow file: PASS or the concrete problems."""
    from .flow import FlowError, load_flow
    from .guards import unknown_rules
    from .tools import REGISTRY
    path = Path(flow_path).expanduser()
    if not path.is_file():
        return [f"flow file not found: {flow_path}"]
    try:
        flow = load_flow(path)
    except (FlowError, ValueError, OSError) as exc:
        return [f"invalid flow: {exc}"]
    problems = [f"unknown tool {t!r}" for t in sorted({s["tool"] for s in flow["steps"]}
                                                      - set(REGISTRY))]
    problems += [f"unknown never-do rule {r!r}"
                 for r in unknown_rules([r["id"] for r in flow["forbidden"]])]
    if problems:
        return [f"invalid flow: {p}" for p in problems]
    return [f"PASS: {flow['name']} ({len(flow['steps'])} steps, "
            f"{len(flow['forbidden'])} never-do rules)"]


def _missing(out_dir: Path, name: str) -> list[str]:
    return [f"{name} not found in {out_dir} — run /plan first."]


def show_text(out_dir: Path, target: str) -> list[str]:
    """Summarize one saved artifact; capped, never a full dump."""
    dv = out_dir / "dv"
    if target in ("review", "status", "summary"):
        return explain_run(out_dir)
    if target in ("interfaces", "interface"):
        doc = _read_json(dv / "interfaces.json")
        if doc is None:
            return _missing(out_dir, "interfaces.json")
        lines = [f"Interface groups: {len(doc.get('groups', []))}"]
        for group in doc.get("groups", [])[:8]:
            signals = [s.get("name", "?") for s in group.get("signals", [])]
            lines.append(f"  {group.get('name', '?')}: {', '.join(signals[:12])}"
                         + ("…" if len(signals) > 12 else ""))
        return lines
    if target in ("registers", "register", "regmap"):
        doc = _read_json(dv / "registers.json")
        if doc is None:
            return _missing(out_dir, "registers.json")
        regs = doc.get("registers", [])
        names = [r.get("abbreviation") or r.get("name", "?") for r in regs]
        return [f"Registers: {len(regs)}",
                f"  {', '.join(names[:20])}" + ("…" if len(names) > 20 else ""),
                f"Configurable fields: {len(doc.get('configurable', []))}"]
    if target == "strategy":
        doc = _read_json(dv / "strategy.json")
        if doc is None:
            return _missing(out_dir, "strategy.json")
        agents = [a.get("name", "?") for a in doc.get("agents", [])]
        return [f"Agents: {', '.join(agents[:12])}" + ("…" if len(agents) > 12 else ""),
                f"Scoreboards: {len(doc.get('scoreboards', []))}, "
                f"gaps: {len(doc.get('gaps', []))}"]
    if target in ("testplan", "test-plan", "plan", "sections"):
        doc = _read_json(dv / "testplan_doc.json")
        if doc is None:
            return _missing(out_dir, "testplan_doc.json")
        lines = [f"Testplan: {doc.get('scope', '(whole spec)')}"]
        for section in doc.get("sections", [])[:14]:
            count = len(section.get("entries", section.get("configurations", [])))
            lines.append(f"  {section.get('id')}: {section.get('status')} ({count} items)")
        return lines
    return [f"Nothing to show for {target!r}. Try: interfaces, registers, strategy, "
            f"testplan, review."]


def rerun_plan(target: str, out: Path, variables: dict) -> tuple[str, dict] | None:
    """Resolve a friendly rerun target to (tool, args), or None if unknown."""
    words = _content_words((target or "").lower())
    tool = RERUN_TOOLS.get(words[0] if words else "")
    if tool is None and words[:2] == ["build", "graph"]:
        tool = "dv_build_graph"
    if tool is None:
        return None
    dv_out = str(out / "dv")
    scope = str(variables.get("scope", ""))
    if tool == "dv_ingest":
        return tool, dict(repo=str(variables.get("repo", "")),
                          out=dv_out, include=list(variables.get("include", [])))
    if tool == "dv_build_graph":
        return tool, dict(out=dv_out)
    if tool in ("dv_interfaces", "dv_registers", "dv_strategy"):
        return tool, dict(out=dv_out, scope=scope)
    if tool == "dv_testplan":
        args = dict(out=dv_out, scope=scope)
        if variables.get("template"):
            args["template"] = str(variables["template"])
        rtl_graph = out / "rtl_graph" / "rtl_graph.json"
        if rtl_graph.is_file():
            args["rtl_graph"] = str(rtl_graph)
        return tool, args
    if tool == "rtl_extract":
        return tool, dict(files=[str(p) for p in variables.get("rtl_files", [])],
                          top=str(variables.get("rtl_top", "")), out=str(out / "rtl"),
                          build=True)
    if tool == "rtl_build_graph":
        files = variables.get("rtl_graph_files") or variables.get("rtl_files", [])
        return tool, dict(files=[str(p) for p in files],
                          top=str(variables.get("rtl_top", "")), out=str(out / "rtl_graph"))
    return None


def rerun_help() -> str:
    return ("supported reruns: " + ", ".join(sorted(set(RERUN_TOOLS))) +
            " — code/uvm stays behind /code")
