"""Live split-pane dashboard for interactive runs.

Right pane lists the flow steps one by one as they run; the left sidebar
shows run counters plus observed token usage on top, and the current tool
call (step, tool, arguments, follow-up question, last decider action) below.
With ANSI unavailable the dashboard degrades to one plain line per event.

Token figures are observed, never estimated: usage blocks are summed from
every trace.jsonl under the run directory. Absence of model calls shows as
zero, not as a guess.
"""
import json
import shutil
import time
from pathlib import Path

GREEN, YELLOW, RED, DIM, RESET = "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[2m", "\x1b[0m"

MARK = {"PASS": ("*", GREEN), "RUN": (">", YELLOW), "....": ("o", DIM),
        "FAIL": ("x", RED), "BLOCKED": ("x", RED), "TIMEOUT": ("x", RED),
        "SKIPPED": ("-", DIM), "NOT_RUN": ("o", DIM)}


def scan_tokens(out_dir) -> dict:
    """Sum usage blocks across trace files. Missing files mean zero calls."""
    calls, tokens = 0, dict(input=0, output=0, cached_input=0)
    try:
        root = Path(out_dir)
        traces = sorted(p for p in root.rglob("trace.jsonl")
                        if len(p.relative_to(root).parts) <= 3)[:20]
    except OSError:
        return dict(calls=0, **tokens)
    for path in traces:
        try:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    try:
                        usage = json.loads(line).get("usage") or {}
                    except ValueError:
                        continue
                    if not isinstance(usage, dict) or "input" not in usage:
                        continue
                    calls += 1
                    for key in tokens:
                        tokens[key] += int(usage.get(key, 0) or 0)
        except OSError:
            continue
    return dict(calls=calls, **tokens)


def _short(value: str, width: int) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= width else value[:max(width - 1, 0)] + "…"


class Dashboard:
    def __init__(self, out_dir, show, *, flow: dict | None = None,
                 title: str = "", ansi: bool = True):
        self.out_dir = out_dir
        self.show = show
        self.flow = flow or {"steps": [], "policy": {}}
        self.title = title
        self.ansi = ansi
        self.steps = [s["id"] for s in self.flow.get("steps", [])]
        self.status = {sid: "...." for sid in self.steps}
        self.summary = {}
        self.current: dict = {}
        self.decider: dict = {}
        self.calls = 0
        self.overrides = 0
        self.invalid = 0
        self.finish: dict = {}
        self.started = time.monotonic()

    def handle(self, event: dict) -> None:
        kind = event.get("event")
        if kind == "run_start":
            self.steps = list(event.get("steps", self.steps))
            self.status = {sid: "...." for sid in self.steps}
        elif kind == "tool_start":
            self.calls += 1
            self.current = {k: event.get(k) for k in
                            ("step", "tool", "attempt", "revisit", "extra_prompt")}
            self.status[event["step"]] = "RUN"
        elif kind == "tool_done":
            self.status[event["step"]] = event.get("status", "?")
            self.summary[event["step"]] = event.get("summary", "")
            if event.get("status") not in ("PASS", "NOT_RUN"):
                self.current = {}
        elif kind == "tool_retry":
            self.status[event["step"]] = "RUN"
        elif kind == "tool_skip_optional":
            self.status[event["step"]] = "SKIPPED"
        elif kind == "decider":
            self.decider = dict(decision=event.get("decision"), error=event.get("error"))
        elif kind == "override":
            self.overrides += 1
        elif kind == "decider_rejected":
            self.invalid += 1
        elif kind in ("guard_block", "review_gate", "budget_exhausted", "config_error"):
            self.finish = dict(status="NEEDS_REVIEW",
                               reason=event.get("step") or event.get("what") or kind)
        elif kind == "run_finish":
            self.finish = dict(status=event.get("status"), reason=event.get("reason", ""))
            self.current = {}
        else:
            return
        self.redraw(kind, event)

    def redraw(self, kind: str | None = None, event: dict | None = None) -> None:
        if not self.ansi:
            self.show(self._plain(kind or "", event or {}))
            return
        width = max(80, min(160, shutil.get_terminal_size((100, 30)).columns))
        left_w, right_w = 34, width - 34 - 7
        left = self._left(left_w)
        right = self._right(right_w)
        rows = max(len(left), len(right))
        bar = "+" + "-" * (left_w + 2) + "+" + "-" * (right_w + 2) + "+"
        lines = ["\x1b[2J\x1b[H" + bar]
        for i in range(rows):
            left_cell = left[i] if i < len(left) else ""
            right_cell = right[i] if i < len(right) else ""
            lines.append(f"| {left_cell.ljust(left_w)} | {right_cell.ljust(right_w)} |")
        lines.append(bar)
        self.show("\n".join(lines))

    def _plain(self, kind: str, event: dict) -> str:
        if kind == "tool_start":
            line = f"{event['step']}: {event['tool']}"
            if event.get("extra_prompt"):
                line += f" (follow-up: {_short(event['extra_prompt'], 80)})"
            return f"[run] {line}"
        if kind == "tool_done":
            return f"[{event.get('status')}] {event['step']}: {event.get('summary', '')}"
        if kind == "decider":
            decision = event.get("decision") or {}
            return f"[decider] {decision.get('action')} {decision.get('target_step', '')}".rstrip()
        if kind in ("guard_block", "review_gate", "budget_exhausted"):
            return f"[gate] {event.get('step') or event.get('what') or kind}"
        if kind == "run_finish":
            return f"[{event.get('status')}] {event.get('reason', '')}"
        return f"[{kind}]"

    def _left(self, width: int) -> list[str]:
        policy = self.flow.get("policy", {})
        tokens = scan_tokens(self.out_dir)
        elapsed = int(time.monotonic() - self.started)
        lines = ["run" + (f": {_short(self.title, width - 5)}" if self.title else ""),
                 f"calls {self.calls}/{policy.get('max_total_tool_calls', '?')}",
                 f"overrides {self.overrides}/{policy.get('max_overrides', '?')} "
                 f"invalid {self.invalid}",
                 f"elapsed {elapsed}s",
                 f"model calls {tokens['calls']}",
                 f"tokens in {tokens['input']} out {tokens['output']} "
                 f"cached {tokens['cached_input']}",
                 "-" * width, "now"]
        if self.finish and not self.current:
            lines += [f"done: {self.finish.get('status')}",
                      _short(self.finish.get("reason", ""), width)]
        elif self.current:
            lines += [f"step: {self.current.get('step')}",
                      f"tool: {_short(self.current.get('tool', ''), width - 6)}",
                      f"try {self.current.get('attempt', 0)} "
                      f"rev {self.current.get('revisit', 0)}"]
            if self.current.get("extra_prompt"):
                lines.append("q: " + _short(self.current["extra_prompt"], width - 3))
        else:
            lines.append("(idle)")
        decision = (self.decider.get("decision") or {}) if self.decider else {}
        if decision:
            lines.append(f"dec: {decision.get('action', '')} "
                         f"{decision.get('target_step', '')}".rstrip())
            if decision.get("reason"):
                lines.append("  " + _short(decision["reason"], width - 2))
        return lines

    def _right(self, width: int) -> list[str]:
        done = sum(1 for sid in self.steps if self.status.get(sid) in ("PASS", "NOT_RUN", "SKIPPED"))
        lines = [f"steps ({done}/{len(self.steps)})"]
        id_w = max(8, width - 12)
        for sid in self.steps:
            status = self.status.get(sid, "....")
            mark, color = MARK.get(status, ("?", DIM))
            if self.ansi:
                mark = f"{color}{mark}{RESET}"
            lines.append(f"{mark} {_short(sid, id_w).ljust(id_w)} {status}")
        return lines
