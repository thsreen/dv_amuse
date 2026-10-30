"""Live three-pane dashboard for interactive runs.

Right pane lists flow steps and testplan substeps; left shows observed usage;
middle shows the current task, progress bar, start time and elapsed time.
With ANSI unavailable the dashboard degrades to one plain line per event.

Token figures are observed, never estimated: usage blocks are summed from
every trace.jsonl under the run directory. Absence of model calls shows as
zero, not as a guess.
"""
import json
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

GREEN, YELLOW, RED, DIM, RESET = "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[2m", "\x1b[0m"
ANSI = re.compile(r"\x1b\[[0-9;]*m")

MARK = {"PASS": ("*", GREEN), "RUN": (">", YELLOW), "....": ("o", DIM),
        "INTERRUPTED": ("x", RED),
        "FAIL": ("x", RED), "BLOCKED": ("x", RED), "TIMEOUT": ("x", RED),
        "SKIPPED": ("-", DIM), "REUSED": ("*", DIM), "NOT_RUN": ("-", DIM)}


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


def _pad_ansi(value: str, width: int) -> str:
    return value + " " * max(0, width - len(ANSI.sub("", value)))


def testplan_substeps() -> list[tuple[str, str]]:
    """Show the template's actual sections, including the two extraction stages."""
    from dv_agent.plan.testplan_doc import load_template
    template = load_template()
    return ([('interfaces', 'Specification interfaces'), ('registers', 'Registers and controls')]
            + [(s['id'], s['heading']) for s in template['sections']]
            + [('render_views', 'Markdown and HTML')])


class Dashboard:
    def __init__(self, out_dir, show, *, flow: dict | None = None,
                 title: str = "", ansi: bool = True, substeps=None, substep_owner=None):
        self.out_dir = out_dir
        self.show = show
        self.flow = flow or {"steps": [], "policy": {}}
        self.title = title
        self.ansi = ansi
        self.steps = [s["id"] for s in self.flow.get("steps", [])]
        self.substep_owner = substep_owner or next((s["id"] for s in self.flow.get("steps", [])
                                   if s.get("tool") == "dv_testplan"), None)
        self.substeps: list[tuple[str, str]] = []
        if substeps is not None:
            self.substeps=list(substeps)
        elif self.substep_owner:
            self.substeps = testplan_substeps()
        self.substatus = {sid: "...." for sid, _ in self.substeps}
        self.status = {sid: "...." for sid in self.steps}
        self.summary = {}
        self.current: dict = {}
        self.decider: dict = {}
        self.calls = 0
        self.overrides = 0
        self.invalid = 0
        self.finish: dict = {}
        self.started = time.monotonic()
        self.started_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.elapsed_s = 0
        self.task_name = "Waiting to start"
        self.task_detail = ""
        self.task_fraction: tuple[int, int] | None = None
        self._lock = threading.RLock()

    def handle(self, event: dict) -> None:
        with self._lock:
            self._handle(event)

    def _handle(self, event: dict) -> None:
        kind = event.get("event")
        if kind in ("substep_done", "tool_done", "run_finish"):
            self.elapsed_s = max(0, int(time.monotonic() - self.started))
        if kind == 'substeps_configured':
            self.substeps=[(s['id'],s['label']) for s in event['steps']]
            self.substatus={sid:self.substatus.get(sid,'....') for sid,label in self.substeps}
        elif kind == "run_start":
            self.steps = list(event.get("steps", self.steps))
            self.status = {sid: "...." for sid in self.steps}
            self.substatus = {sid: "...." for sid, _ in self.substeps}
        elif kind == "tool_start":
            self.calls += 1
            self.current = {k: event.get(k) for k in
                            ("step", "tool", "attempt", "revisit", "extra_prompt")}
            self.status[event["step"]] = "RUN"
            self.task_name = self._step_label(event["step"])
            self.task_detail = ""
            self.task_fraction = None
        elif kind == "tool_done":
            self.status[event["step"]] = event.get("status", "?")
            self.summary[event["step"]] = event.get("summary", "")
            if event["step"] == self.substep_owner and event.get("status") == "PASS":
                for sid in self.substatus:
                    if self.substatus[sid] == "....":
                        self.substatus[sid] = 'NOT_RUN' if self.substep_owner=='code' else "REUSED"
            elif event['step']==self.substep_owner:
                for sid,status in self.substatus.items():
                    if status=='RUN': self.substatus[sid]=event.get('status','FAIL')
            if event.get("status") not in ("PASS", "NOT_RUN"):
                self.current = {}
            self.task_name = self._step_label(event["step"])
            self.task_detail = event.get("summary", "")
        elif kind == "substeps_reused":
            for sid in self.substatus:
                if sid != "render_views" and self.substatus[sid] == "....":
                    self.substatus[sid] = "REUSED"
            self.task_name = "Reuse saved testplan"
        elif kind == "substep_start":
            sid = event.get("id")
            if sid in self.substatus:
                self.substatus[sid] = "RUN"
            self.task_name = event.get("label") or self._substep_label(sid)
            self.task_detail = ""
            self.task_fraction = None
        elif kind == "substep_done":
            sid = event.get("id")
            if sid in self.substatus:
                self.substatus[sid] = event.get("status", "PASS")
            self.task_name = event.get("label") or self._substep_label(sid)
            self.task_detail = event.get("status", "")
        elif kind == "task_progress":
            self.task_detail = event.get("message", "")
            match = re.search(r"\[(\d+)/(\d+)\]", self.task_detail)
            if match and int(match[2]) > 0:
                self.task_fraction = (min(int(match[1]), int(match[2])), int(match[2]))
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
            self.task_name = "Run finished"
            self.task_detail = event.get("reason", "")
        else:
            return
        self.redraw(kind, event)

    def _step_label(self, sid: str) -> str:
        item = next((s for s in self.flow.get("steps", []) if s["id"] == sid), None)
        return item.get("description", sid) if item else sid

    def _substep_label(self, sid: str | None) -> str:
        return next((label for key, label in self.substeps if key == sid), sid or "")

    def redraw(self, kind: str | None = None, event: dict | None = None) -> None:
        with self._lock:
            self._redraw(kind, event)

    def _redraw(self, kind: str | None = None, event: dict | None = None) -> None:
        if not self.ansi:
            if kind:
                self.show(self._plain(kind, event or {}))
            return
        width = max(80, min(180, shutil.get_terminal_size((120, 30)).columns))
        left_w, middle_w = max(22, width // 4), max(28, width // 3)
        right_w = width - left_w - middle_w - 10
        left = self._left(left_w)
        middle = self._middle(middle_w)
        right = self._right(right_w)
        rows = max(len(left), len(middle), len(right))
        bar = "+" + "-" * (left_w + 2) + "+" + "-" * (middle_w + 2) + "+" + "-" * (right_w + 2) + "+"
        lines = ["\x1b[2J\x1b[H" + bar]
        for i in range(rows):
            left_cell = left[i] if i < len(left) else ""
            middle_cell = middle[i] if i < len(middle) else ""
            right_cell = right[i] if i < len(right) else ""
            lines.append(f"| {_short(left_cell, left_w).ljust(left_w)} | {_short(middle_cell, middle_w).ljust(middle_w)} | {_pad_ansi(right_cell, right_w)} |")
        lines.append(bar)
        self.show("\n".join(lines))

    def _plain(self, kind: str, event: dict) -> str:
        if kind == 'run_start' and self.substep_owner == 'code':
            return f"[started] {self.started_utc}"
        if kind == "tool_start":
            line = f"{event['step']}: {event['tool']}"
            if event.get("extra_prompt"):
                line += f" (follow-up: {_short(event['extra_prompt'], 80)})"
            return f"[run] {line}"
        if kind == "tool_done":
            return f"[{event.get('status')}] {event['step']}: {event.get('summary', '')}"
        if kind == "substep_start":
            return f"[run] {event.get('label') or self._substep_label(event.get('id'))}"
        if kind == "substep_done":
            return f"[{event.get('status')}] {self._substep_label(event.get('id'))}"
        if kind == "task_progress":
            return f"[progress] {event.get('message', '')}"
        if kind == "substeps_reused":
            return "[reused] saved testplan sections"
        if kind == 'substeps_configured': return f"[steps] {len(event['steps'])} code tasks identified"
        if kind == "decider":
            decision = event.get("decision") or {}
            return f"[decider] {decision.get('action')} {decision.get('target_step', '')}".rstrip()
        if kind in ("guard_block", "review_gate", "budget_exhausted"):
            return f"[gate] {event.get('step') or event.get('what') or kind}"
        if kind == "run_finish":
            elapsed = f" (elapsed {event['elapsed_s']:.1f}s)" if 'elapsed_s' in event else ''
            return f"[{event.get('status')}] {event.get('reason', '')}{elapsed}"
        return f"[{kind}]"

    def _left(self, width: int) -> list[str]:
        policy = self.flow.get("policy", {})
        tokens = scan_tokens(self.out_dir)
        lines = ["run" + (f": {_short(self.title, width - 5)}" if self.title else ""),
                 f"calls {self.calls}/{policy.get('max_total_tool_calls', '?')}",
                 f"overrides {self.overrides}/{policy.get('max_overrides', '?')} "
                 f"invalid {self.invalid}",
                 f"elapsed {self.elapsed_s}s",
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
                      f"rev {self.current.get('revisit') or 0}"]
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

    def _middle(self, width: int) -> list[str]:
        complete = {"PASS", "NOT_RUN", "SKIPPED", "REUSED"}
        units = [self.status.get(sid, "....") for sid in self.steps if sid != self.substep_owner]
        units += list(self.substatus.values()) if self.substep_owner else []
        done = sum(status in complete for status in units)
        total = len(units)
        percent = round(100 * done / total) if total else 0
        bar_w = max(8, width - 8)
        filled = round(bar_w * done / total) if total else 0
        hours, rem = divmod(self.elapsed_s, 3600)
        minutes, seconds = divmod(rem, 60)
        return ["progress", f"{done}/{total} tasks complete",
                "[" + "#" * filled + "-" * (bar_w - filled) + f"] {percent}%",
                "-" * width, "current task",
                _short(self.task_name, width),
                _short(self.task_detail, width) if self.task_detail else "(waiting for task output)",
                "task progress",
                ("[" + "#" * round(bar_w * self.task_fraction[0] / self.task_fraction[1])
                 + "-" * (bar_w - round(bar_w * self.task_fraction[0] / self.task_fraction[1]))
                 + f"] {self.task_fraction[0]}/{self.task_fraction[1]}"
                 if self.task_fraction else "awaiting next checkpoint"),
                "-" * width, "started", self.started_utc,
                "elapsed", f"{hours:02d}:{minutes:02d}:{seconds:02d}"]

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
            if sid == self.substep_owner:
                for subid, label in self.substeps:
                    substatus = self.substatus.get(subid, "....")
                    marker, color = MARK.get(substatus, ("?", DIM))
                    if self.ansi:
                        marker = f"{color}{marker}{RESET}"
                    text = _short(label, max(5, id_w - 2))
                    lines.append(f"  {marker} {text.ljust(max(5, id_w - 2))} {substatus}")
        if self.substep_owner=='code':
            budget=max(18,shutil.get_terminal_size((120,30)).lines-4)
            if len(lines)>budget:
                current=next((i for i,line in enumerate(lines) if ' RUN' in line and i>1),len(lines)-1)
                start=max(1,min(current-3,len(lines)-budget+2))
                lines=[lines[0],f'({start} earlier rows; full details in code trace)']+lines[start:start+budget-3]
        return lines
