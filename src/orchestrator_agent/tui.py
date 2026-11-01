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
import textwrap
from datetime import datetime, timezone
from pathlib import Path

GREEN, YELLOW, RED, DIM, RESET = "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[2m", "\x1b[0m"
ANSI = re.compile(r"\x1b\[[0-9;]*m")

MARK = {"PASS": ("*", GREEN), "RUN": (">", YELLOW), "....": ("o", DIM),
        "WAITING_HUMAN": ("?", YELLOW), "PLAN_UPDATED": ("*", GREEN),
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


def _wrap(value: str, width: int) -> list[str]:
    """Retain complete task messages, including long identifiers and explicit lines."""
    wrapper = textwrap.TextWrapper(width=max(1, width), break_on_hyphens=False)
    return [line for paragraph in str(value).split("\n")
            for line in (wrapper.wrap(paragraph) or [""])]


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
        self.sub_parent: dict[str, str] = {}  # sub-step id -> id of the group header it is a bullet of
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
        self._failed = {}
        self._retry_counts = {}
        self._retry_active = set()
        self.active_substep = None
        self.review_presenting = False
        self._restore_retries()

    def _restore_retries(self):
        path = Path(self.out_dir) / ('code_trace.jsonl' if self.substep_owner == 'code' else 'orchestrator_trace.jsonl')
        active_sub = active_tool = None
        try:
            with path.open() as handle:
                for line in handle:
                    try: event = json.loads(line)
                    except ValueError: continue
                    if not isinstance(event,dict): continue
                    kind = event.get('event')
                    if kind in ('tool_done','substep_done','tool_interrupted'):
                        key = ('tool',event.get('step')) if kind.startswith('tool') else ('sub',event.get('id'))
                        self._finished(key,event.get('status','INTERRUPTED'))
                        if kind=='substep_done': active_sub=None
                    elif kind in ('tool_start','substep_start'):
                        key = ('tool',event.get('step')) if kind == 'tool_start' else ('sub',event.get('id'))
                        self._starting(key)
                        if kind=='substep_start': active_sub=event.get('id')
                        else: active_tool=event.get('step')
                    elif kind in ('tool_retry','substep_retry'):
                        key = ('tool',event.get('step')) if kind == 'tool_retry' else ('sub',event.get('id'))
                        self._retry(key,event.get('status','FAIL'))
                    elif kind=='task_retry' and (active_sub or active_tool):
                        key=('sub',active_sub) if active_sub else ('tool',active_tool)
                        self._retry(key,event.get('status','FAIL'))
        except OSError:
            pass
        self._retry_active.clear()

    def _finished(self, key, status):
        self._retry_active.discard(key)
        if status not in ('PASS','NOT_RUN','SKIPPED','REUSED','PLAN_UPDATED'):
            self._failed[key] = status
        else:
            self._failed.pop(key,None)
            self._retry_counts.pop(key,None)

    def _retry(self, key, previous):
        self._failed[key] = previous
        self._retry_counts[key] = self._retry_counts.get(key,0) + 1
        self._retry_active.add(key)

    def _starting(self, key):
        if key in self._failed and key not in self._retry_active:
            self._retry(key,self._failed[key])

    def _display_status(self, key, status):
        if status == 'RUN' and key in self._retry_active:
            return f"{self._failed[key]}/RETRY({self._retry_counts[key]})"
        return status

    def handle(self, event: dict) -> None:
        with self._lock:
            self._handle(event)

    def _handle(self, event: dict) -> None:
        kind = event.get("event")
        if kind=='review_presentation_start':
            self.review_presenting=True
            if self.ansi: self.show('\x1b[2J\x1b[H')
            return
        if kind=='review_presentation_end':
            self.review_presenting=False
            self.redraw()
            return
        if kind in ("substep_done", "tool_done", "run_finish"):
            self.elapsed_s = max(0, int(time.monotonic() - self.started))
        if kind=='notification_start':
            if 'startup_notification' not in self.steps: self.steps.insert(0,'startup_notification')
            self.status['startup_notification']='RUN'
            self.task_name='Send startup notification to Hermes/Telegram'
            self.task_detail=''
        elif kind=='notification_done':
            self.status['startup_notification']='PASS' if event.get('status')=='SENT' else 'NOT_RUN'
            self.summary['startup_notification']=event.get('reason') or event.get('status')
            self.task_detail='Notification: '+event.get('status','')
        elif kind == 'substeps_configured':
            self.substeps=[(s['id'],s['label']) for s in event['steps']]
            self.sub_parent={s['id']:s['parent'] for s in event['steps'] if s.get('parent')}
            self.substatus={sid:self.substatus.get(sid,'....') for sid,label in self.substeps}
        elif kind == "run_start":
            self.active_substep = None
            self._retry_active.clear()
            self.steps = list(event.get("steps", self.steps))
            self.status = {sid: "...." for sid in self.steps}
            self.substatus = {sid: "...." for sid, _ in self.substeps}
        elif kind == "tool_start":
            self._starting(('tool',event['step']))
            self.calls += 1
            self.current = {k: event.get(k) for k in
                            ("step", "tool", "attempt", "revisit", "extra_prompt")}
            self.status[event["step"]] = "RUN"
            self.task_name = self._step_label(event["step"])
            self.task_detail = ""
            self.task_fraction = None
        elif kind == "tool_done":
            self._finished(('tool',event['step']),event.get('status','FAIL'))
            self.status[event["step"]] = event.get("status", "?")
            self.summary[event["step"]] = event.get("summary", "")
            if event["step"] == self.substep_owner and event.get("status") == "PASS":
                for sid in self.substatus:
                    if self.substatus[sid] == "....":
                        self.substatus[sid] = 'NOT_RUN' if self.substep_owner=='code' else "REUSED"
            elif event['step']==self.substep_owner:
                for sid,status in self.substatus.items():
                    if status=='RUN':
                        self.substatus[sid]=event.get('status','FAIL')
                        self._finished(('sub',sid),event.get('status','FAIL'))
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
            self.active_substep = sid
            self._starting(('sub',sid))
            if sid in self.substatus:
                self.substatus[sid] = "RUN"
            self.task_name = event.get("label") or self._substep_label(sid)
            self.task_detail = ""
            self.task_fraction = None
        elif kind == "substep_done":
            sid = event.get("id")
            self._finished(('sub',sid),event.get('status','PASS'))
            if self.active_substep == sid: self.active_substep = None
            if sid in self.substatus:
                self.substatus[sid] = event.get("status", "PASS")
            self.task_name = event.get("label") or self._substep_label(sid)
            self.task_detail = event.get("status", "")
        elif kind == 'human_review':
            sid=event.get('id')
            if sid in self.substatus: self.substatus[sid]='WAITING_HUMAN'
            self.task_name='Human clarification required'
            self.task_detail=event.get('question','')
        elif kind == "task_progress":
            self.task_detail = event.get("message", "")
            match = re.search(r"\[(\d+)/(\d+)\]", self.task_detail)
            if match and int(match[2]) > 0:
                self.task_fraction = (min(int(match[1]), int(match[2])), int(match[2]))
        elif kind == "tool_retry":
            self._retry(('tool',event['step']),event.get('status','FAIL'))
            self.status[event["step"]] = "RUN"
        elif kind in ('substep_retry','task_retry'):
            sid = event.get('id') or self.active_substep
            if sid:
                self._retry(('sub',sid),event.get('status','FAIL'))
                self.substatus[sid] = 'RUN'
            elif self.current:
                self._retry(('tool',self.current['step']),event.get('status','FAIL'))
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
            self.active_substep = None
            self._retry_active.clear()
            self.finish = dict(status=event.get("status"), reason=event.get("reason", ""))
            self.current = {}
            self.task_name = "Run finished"
            self.task_detail = event.get("reason", "")
        else:
            return
        self.redraw(kind, event)

    def _step_label(self, sid: str) -> str:
        if sid=='startup_notification': return 'Startup notification'
        item = next((s for s in self.flow.get("steps", []) if s["id"] == sid), None)
        return item.get("description", sid) if item else sid

    def _group_status(self, header: str) -> str:
        """A group header shows its sub-steps' combined state: the first problem, else running, else done."""
        states = [self.substatus.get(sid, '....') for sid, parent in self.sub_parent.items() if parent == header]
        problem = next((st for st in states if st not in ('PASS','NOT_RUN','SKIPPED','REUSED','PLAN_UPDATED','RUN','....','WAITING_HUMAN')), None)
        if problem: return problem
        if 'WAITING_HUMAN' in states: return 'WAITING_HUMAN'
        if all(st in ('PASS','NOT_RUN','SKIPPED','REUSED','PLAN_UPDATED') for st in states) and states: return 'PASS'
        return 'RUN' if any(st != '....' for st in states) else '....'

    def _substep_label(self, sid: str | None) -> str:
        return next((label for key, label in self.substeps if key == sid), sid or "")

    def redraw(self, kind: str | None = None, event: dict | None = None) -> None:
        with self._lock:
            self._redraw(kind, event)

    def _redraw(self, kind: str | None = None, event: dict | None = None) -> None:
        if self.review_presenting: return
        if not self.ansi:
            if kind:
                self.show(self._plain(kind, event or {}))
            return
        width = max(4, min(180, shutil.get_terminal_size((120, 30)).columns))
        if width < 80:
            # A three-column minimum would overflow narrow terminals and hide statuses.
            content_w = max(1, width - 4)
            bar = "+" + "-" * (content_w + 2) + "+"
            lines = ["\x1b[2J\x1b[H" + bar]
            # Keep the current task at the bottom, visible when the terminal scrolls.
            for pane in (self._left(content_w), self._right(content_w), self._middle(content_w)):
                for row in pane:
                    lines.extend(f"| {part.ljust(content_w)} |" for part in _wrap(ANSI.sub("", row), content_w))
                lines.append(bar)
            self.show("\n".join(lines))
            return
        left_w, middle_w = max(22, width // 4), max(28, width // 3)
        right_w = width - left_w - middle_w - 10
        left = self._left(left_w)
        middle = self._middle(middle_w)
        right = self._right(right_w)
        right = [part for row in right for part in
                 (_wrap(ANSI.sub("", row), right_w) if len(ANSI.sub("", row)) > right_w else [row])]
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
        if kind=='notification_start': return '[run] Send startup notification to Hermes/Telegram'
        if kind=='notification_done': return f"[notification {event.get('status')}] {event.get('reason','')}"
        if kind=='human_review': return f"[WAITING_HUMAN] {event.get('question','')} ({event.get('request_id','')})"
        if kind == 'run_start' and self.substep_owner == 'code':
            return f"[started] {self.started_utc}"
        if kind == "tool_start":
            line = f"{event['step']}: {event['tool']}"
            if event.get("extra_prompt"):
                line += f" (follow-up: {_short(event['extra_prompt'], 80)})"
            status=self._display_status(('tool',event['step']),'RUN')
            return f"[{status if status!='RUN' else 'run'}] {line}"
        if kind == "tool_done":
            return f"[{event.get('status')}] {event['step']}: {event.get('summary', '')}"
        if kind == "substep_start":
            status=self._display_status(('sub',event.get('id')),'RUN')
            bullet = '  - ' if event.get('id') in self.sub_parent else ''
            return f"[{status if status!='RUN' else 'run'}] {bullet}{event.get('label') or self._substep_label(event.get('id'))}"
        if kind == "substep_done":
            bullet = '  - ' if event.get('id') in self.sub_parent else ''
            return f"[{event.get('status')}] {bullet}{self._substep_label(event.get('id'))}"
        if kind in ('tool_retry','substep_retry','task_retry'):
            key=('tool',event['step']) if kind=='tool_retry' else ('sub',event.get('id') or self.active_substep)
            if key[1] is None and self.current: key=('tool',self.current['step'])
            return f"[{self._display_status(key,'RUN')}] {key[1] or self.task_name}"
        if kind == "task_progress":
            return f"[progress] {event.get('message', '')}"
        if kind == "substeps_reused":
            return "[reused] saved testplan sections"
        if kind == 'substeps_configured':
            lines = [f"[steps] {len(event['steps'])} code tasks identified"]
            lines += [('    - ' if s.get('parent') else '  * ') + s['label'] for s in event['steps'] if s.get('parent') or s['id'].startswith('group:')]
            return '\n'.join(lines)
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
        current_key=('sub',self.active_substep) if self.active_substep else ('tool',self.current.get('step'))
        retry_status=self._display_status(current_key,'RUN')
        lines = ["progress", f"{done}/{total} tasks complete",
                "[" + "#" * filled + "-" * (bar_w - filled) + f"] {percent}%",
                "-" * width, "current task",
                self.task_name,
                *( [retry_status] if retry_status!='RUN' else []),
                self.task_detail if self.task_detail else "(waiting for task output)",
                "task progress",
                ("[" + "#" * round(bar_w * self.task_fraction[0] / self.task_fraction[1])
                 + "-" * (bar_w - round(bar_w * self.task_fraction[0] / self.task_fraction[1]))
                 + f"] {self.task_fraction[0]}/{self.task_fraction[1]}"
                 if self.task_fraction else "awaiting next checkpoint"),
                "-" * width, "started", self.started_utc,
                "elapsed", f"{hours:02d}:{minutes:02d}:{seconds:02d}"]
        return [part for line in lines for part in _wrap(line, width)]

    def _right(self, width: int) -> list[str]:
        done = sum(1 for sid in self.steps if self.status.get(sid) in ("PASS", "NOT_RUN", "SKIPPED"))
        lines = [f"steps ({done}/{len(self.steps)})"]
        id_w = max(8, width - 12)
        for sid in self.steps:
            status = self.status.get(sid, "....")
            mark, color = MARK.get(status, ("?", DIM))
            if self.ansi:
                mark = f"{color}{mark}{RESET}"
            display=self._display_status(('tool',sid),status)
            label_width=max(1,width-len(display)-3)
            lines.append(f"{mark} {_short(sid,label_width).ljust(label_width)} {display}")
            if sid == self.substep_owner:
                for subid, label in self.substeps:
                    child = subid in self.sub_parent
                    substatus = self._group_status(subid) if subid in self.sub_parent.values() else self.substatus.get(subid, "....")
                    marker, color = MARK.get(substatus, ("?", DIM))
                    if self.ansi:
                        marker = f"{color}{marker}{RESET}"
                    display=substatus if subid in self.sub_parent.values() else self._display_status(('sub',subid),substatus)
                    indent = "    " if child else "  "   # sub-bullets sit under their group header
                    label_width=max(1,width-len(display)-3-len(indent))
                    text = _short(label,label_width)
                    lines.append(f"{indent}{marker} {text.ljust(label_width)} {display}")
        if self.substep_owner=='code':
            budget=max(18,shutil.get_terminal_size((120,30)).lines-4)
            if len(lines)>budget:
                current=next((i for i,line in enumerate(lines) if (' RUN' in line or '/RETRY(' in line) and i>1),len(lines)-1)
                start=max(1,min(current-3,len(lines)-budget+2))
                lines=[lines[0],f'({start} earlier rows; full details in code trace)']+lines[start:start+budget-3]
        return lines
