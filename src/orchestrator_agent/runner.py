"""Step-by-step execution loop with loop counters, timeouts and owner gates.

The runner follows the flow's recommended order. A bounded model decider may
revisit a completed step with a sharper follow-up question, skip an optional
step, or stop. Every budget exhaustion, timeout, guard violation and review
gate reverts to the owner with a review file and a resume command.
"""
import concurrent.futures
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import decider as decider_mod
from . import guards
from .flow import FlowError, load_flow, resolve_args
from .tools import REGISTRY, RTL_BEHAVIOR, StepContext

TRACE_FILE = "orchestrator_trace.jsonl"
RESULT_FILE = "orchestrator_result.json"
REVIEW_FILE = "orchestrator_review.json"
ASK_FILE = "orchestrator_ask.json"

SINGLE_TOOL_TIMEOUT_S = 600.0

# Markers that prove a directory is an orchestrator run dir. reset_out_dir
# refuses to clear a non-empty directory without one of these.
RUN_MARKERS = (ASK_FILE, TRACE_FILE, RESULT_FILE, REVIEW_FILE, "dv", "rtl",
               "rtl_graph", "rtl_spec", "uvm", "code")


def reset_out_dir(out_dir: Path | str) -> list[str]:
    """Delete every cached/derived entry in an orchestrator run directory.

    Returns the cleared top-level names. Refuses a non-empty directory with
    no run markers, so a mistyped --out cannot wipe an unrelated folder.
    """
    out = Path(out_dir)
    if not out.exists():
        out.mkdir(parents=True, exist_ok=True)
        return []
    entries = sorted(out.iterdir(), key=lambda p: p.name)
    if entries and not any((out / marker).exists() for marker in RUN_MARKERS):
        raise ValueError(f"{out} has no orchestrator run markers; refusing to clear it")
    import shutil
    cleared = []
    for child in entries:
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
        cleared.append(child.name)
    return cleared


def run_single_tool(tool: str, args: dict, *, out_dir: Path | str, llm=None,
                    embedder=None, extra_prompt: str = "", force: bool = False,
                    registry: dict | None = None,
                    timeout_s: float = SINGLE_TOOL_TIMEOUT_S) -> dict:
    """Execute one registry tool outside the flow order, guards enforced.

    Used by the terminal for adjacent asks ("rerun registers"). Unknown tools
    and guard violations return BLOCKED without executing anything; the call
    is appended to the run trace for audit.
    """
    specs = registry if registry is not None else REGISTRY
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / TRACE_FILE

    def emit(event: str, **fields):
        record = dict(ts=_now(), event=event, **fields)
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")

    if tool not in specs:
        summary = f"NO_NEW_TOOLS: unknown tool {tool!r}"
        emit("guard_block", tool=tool, violations=[summary])
        return dict(status="BLOCKED", summary=summary, files=[])
    spec = specs[tool]
    violations = guards.pre_tool_check(
        tool=tool, args=args, extra_prompt=extra_prompt, out_dir=out_dir,
        rtl_behavior_files=set())
    if violations:
        emit("guard_block", tool=tool, violations=violations)
        return dict(status="BLOCKED", summary=violations[0], files=[])
    if spec.needs_llm and llm is None:
        return dict(status="BLOCKED", summary=f"{tool} needs MODEL_API_KEY", files=[])
    emit("single_tool_start", tool=tool, args=args)
    context = StepContext(out_dir=out_dir, llm=llm, embedder=embedder,
                          extra_prompt=extra_prompt, force=force)
    if tool in ("dv_build_graph", "dv_testplan"):
        # Checkpointed model stages: wait for completion like the flow loop.
        result = spec.run(args, context)
    else:
        outcome, value = call_with_timeout(lambda: spec.run(args, context), timeout_s)
        result = value if outcome == "ok" else dict(
            status="TIMEOUT", summary=f"{tool} exceeded {timeout_s:g}s", files=[])
    emit("single_tool_done", tool=tool, status=result.get("status", "FAIL"),
         summary=result.get("summary", ""))
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def call_with_timeout(fn, timeout_s: float):
    """Run fn in a worker thread; return ("ok", value) or ("timeout", None).

    A timeout stops waiting, not the worker: the thread lingers until the
    tool returns. The run moves on to the owner gate instead of hanging.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(fn)
        try:
            return "ok", future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            future.cancel()
            return "timeout", None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def run_flow(flow_path: Path | str, *, out_dir: Path | str, variables: dict,
             llm=None, embedder=None, approvals=(), dry_run: bool = False,
             force: bool = False, registry: dict | None = None,
             resume_hint: str | None = None, event_sink=None) -> dict:
    """Execute a flow file step by step. Returns the result (also on disk).

    event_sink, when given, receives a copy of every trace event as it fires
    (used by the live dashboard); trace-file output is unchanged.
    """
    flow = load_flow(Path(flow_path))
    specs = registry if registry is not None else REGISTRY
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / TRACE_FILE

    def emit(event: str, **fields):
        record = dict(ts=_now(), event=event, **fields)
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
        if event_sink is not None:
            event_sink(record)

    variables = dict(variables)
    variables.setdefault("out", str(out_dir))
    repo = variables.get("repo")
    order: list[dict] = flow["steps"]
    policy: dict = flow["policy"]
    by_id = {s["id"]: s for s in order}
    approved = set(approvals)
    history: list[dict] = []
    step_records: dict[str, dict] = {}
    file_tags: dict[str, str] = {}
    blocked_violations: list[str] = []
    runs: dict[str, int] = {}
    revisits: dict[str, int] = {}
    overrides_used = 0
    invalid_decisions = 0
    tool_calls = 0
    started = time.monotonic()
    emit("run_start", flow=str(flow_path), steps=[s["id"] for s in order],
         dry_run=dry_run, approvals=sorted(approved))

    def finish(status: str, reason: str = "", *, approvals_needed=None,
               question: str = "", pending: str | None = None) -> dict:
        result = dict(
            flow=str(flow_path), out=str(out_dir), status=status, reason=reason,
            dry_run=dry_run, tool_calls=tool_calls, overrides_used=overrides_used,
            invalid_decider_proposals=invalid_decisions,
            approvals=sorted(approved), violations=blocked_violations,
            steps=[dict(id=s["id"], tool=s["tool"],
                        status=step_records.get(s["id"], {}).get("status", "NOT_RUN"),
                        attempts=runs.get(s["id"], 0),
                        revisits=revisits.get(s["id"], 0),
                        summary=step_records.get(s["id"], {}).get("summary", ""))
                   for s in order],
            trace=str(trace_path))
        (out_dir / RESULT_FILE).write_text(json.dumps(result, indent=2), encoding="utf-8")
        emit("run_finish", status=status, reason=reason)
        if status != "PASS":
            review = dict(
                status="BLOCKED" if status == "BLOCKED" else "NEEDS_REVIEW",
                reason=reason, question=question or
                "Review the trace and decide whether the run may continue.",
                pending_step=pending, approvals_needed=approvals_needed or [],
                approvals_given=sorted(approved),
                resume=((resume_hint + " " if resume_hint else
                         f"orchestrate-agent run --flow {flow_path} --out {out_dir} ")
                        + (f"--approve {','.join(approvals_needed)}"
                           if approvals_needed else "--approve <step-id>")),
                budgets=dict(tool_calls=tool_calls,
                             max_total_tool_calls=policy["max_total_tool_calls"],
                             overrides_used=overrides_used,
                             max_overrides=policy["max_overrides"]),
                violations=blocked_violations, history=history[-10:])
            (out_dir / REVIEW_FILE).write_text(json.dumps(review, indent=2), encoding="utf-8")
        return result

    # Fail closed on flow bugs before executing anything.
    unknown_tools = sorted({s["tool"] for s in order if s["tool"] not in specs})
    if unknown_tools:
        emit("config_error", unknown_tools=unknown_tools)
        return finish("BLOCKED", f"unknown tools in flow: {', '.join(unknown_tools)}",
                      question="Fix the flow file to use only supported tools, then rerun.")
    unknown = guards.unknown_rules([r["id"] for r in flow["forbidden"]])
    if unknown:
        emit("config_error", unknown_forbidden=unknown)
        return finish("BLOCKED", f"unknown never-do rules (fail closed): {', '.join(unknown)}",
                      question="Remove or correct the unknown rule IDs, then rerun.")
    if repo and str(repo).strip():
        try:
            same = Path(str(repo)).resolve() == out_dir.resolve()
        except OSError:
            same = False
        if same:
            emit("guard_block", rule="NO_DESIGN_MUTATION")
            return finish(
                "BLOCKED", "NO_DESIGN_MUTATION: output directory equals the source repo",
                question="Rerun with --out pointing at a fresh run directory.")

    completed: set[str] = set()
    index = 0
    pending_revisit: tuple[str, str] | None = None

    while True:
        if pending_revisit is not None:
            step_id, extra_prompt = pending_revisit
            step = by_id[step_id]
            is_revisit = True
        elif index < len(order):
            step = order[index]
            step_id, extra_prompt = step["id"], ""
            is_revisit = False
        else:
            break
        tool = step["tool"]
        if time.monotonic() - started > policy["global_timeout_s"]:
            emit("budget_exhausted", what="global_timeout")
            return finish(
                "NEEDS_REVIEW",
                f"global timeout ({policy['global_timeout_s']}s) before step {step_id!r}",
                pending=step_id, approvals_needed=[step_id],
                question=f"Step {step_id!r} was not reached in time. Approve it to "
                         f"resume the run with a fresh budget.")
        if step.get("review_gate") and step_id not in approved:
            emit("review_gate", step=step_id)
            return finish(
                "NEEDS_REVIEW", f"step {step_id!r} needs owner approval (review_gate)",
                pending=step_id, approvals_needed=[step_id],
                question=f"Approve step {step_id!r} ({tool}) to let it run.")
        if is_revisit:
            revisits[step_id] = revisits.get(step_id, 0) + 1
            if revisits[step_id] > policy["max_revisits_per_step"]:
                emit("budget_exhausted", what="revisits", step=step_id)
                return finish(
                    "NEEDS_REVIEW", f"revisit budget for step {step_id!r} spent",
                    pending=step_id, approvals_needed=[step_id],
                    question=f"Step {step_id!r} was revisited "
                             f"{policy['max_revisits_per_step']} time(s) already. Approve it "
                             f"to grant another revisit round.")
        else:
            runs[step_id] = runs.get(step_id, 0) + 1
            if runs[step_id] > step["max_attempts"]:
                emit("budget_exhausted", what="attempts", step=step_id)
                return finish(
                    "NEEDS_REVIEW",
                    f"step {step_id!r} failed {step['max_attempts']} time(s)",
                    pending=step_id, approvals_needed=[step_id],
                    question=f"Step {step_id!r} kept failing. Fix the cause, then "
                             f"approve it to run again.")
        tool_calls += 1
        if tool_calls > policy["max_total_tool_calls"]:
            emit("budget_exhausted", what="total_tool_calls")
            return finish(
                "NEEDS_REVIEW",
                f"total tool-call budget ({policy['max_total_tool_calls']}) spent",
                pending=step_id, approvals_needed=[step_id],
                question="The run executed too many tool calls (possible loop). "
                         "Approve the pending step to continue with a fresh budget.")
        try:
            args = resolve_args(step.get("args", {}), variables, step_id)
        except FlowError as exc:
            emit("config_error", step=step_id, error=str(exc))
            return finish("NEEDS_REVIEW", f"step {step_id!r}: {exc}",
                          pending=step_id, approvals_needed=[step_id],
                          question="Supply the missing variable with --var/--option, "
                                   "then approve the step to resume.")
        spec = specs[tool]
        if spec.agent != step["agent"]:
            emit("config_error", step=step_id)
            return finish(
                "NEEDS_REVIEW",
                f"step {step_id!r} declares agent {step['agent']!r} but tool "
                f"{tool!r} belongs to {spec.agent!r}",
                pending=step_id, approvals_needed=[step_id],
                question="Fix the step's agent field, then approve it to resume.")
        rtl_behavior_files = {p for p, t in file_tags.items() if t == RTL_BEHAVIOR}
        violations = guards.pre_tool_check(
            tool=tool, args=args, extra_prompt=extra_prompt, out_dir=out_dir,
            rtl_behavior_files=rtl_behavior_files)
        if violations:
            blocked_violations.extend(f"{step_id}: {v}" for v in violations)
            emit("guard_block", step=step_id, violations=violations)
            return finish(
                "NEEDS_REVIEW",
                f"strict never-do rule blocked step {step_id!r}: {violations[0]}",
                pending=step_id, approvals_needed=[step_id],
                question="A strict rule fired. Change the flow or inputs so the "
                         "rule holds, then approve the step to run again.")
        if spec.needs_llm and llm is None and not dry_run:
            summary = f"{tool} needs MODEL_API_KEY"
            step_records[step_id] = dict(status="BLOCKED", summary=summary)
            history.append(dict(step=step_id, tool=tool, status="BLOCKED",
                                summary=summary, attempt=runs[step_id]))
            emit("tool_done", step=step_id, status="BLOCKED", summary=summary)
            if step.get("optional"):
                step_records[step_id] = dict(status="SKIPPED", summary=summary)
                index = index + 1 if not is_revisit else index
                pending_revisit = None
                continue
            return finish("NEEDS_REVIEW", f"step {step_id!r}: {summary}",
                          pending=step_id, approvals_needed=[step_id],
                          question="Set MODEL_API_KEY (or switch the flow to offline "
                                   "steps), then approve the step to run again.")
        emit("tool_start", step=step_id, tool=tool, attempt=runs.get(step_id, 0),
             revisit=revisits.get(step_id, 0),
             extra_prompt=extra_prompt or None, request_timeout_s=getattr(llm,'timeout',None),
             request_attempts=getattr(llm,'max_attempts',None))
        tool_started = time.monotonic()
        if dry_run:
            result = dict(status="NOT_RUN", summary="dry run", files=[])
        else:
            context = StepContext(out_dir=out_dir, llm=llm, embedder=embedder,
                                  extra_prompt=extra_prompt, force=force)
            def invoke():
                if spec.agent != "dv":
                    return spec.run(args, context)
                from dv_agent.core import progress
                progress.set_sink(lambda message: emit("task_progress", step=step_id, message=message))
                progress.set_event_sink(lambda detail: emit(
                    detail["kind"], step=step_id,
                    **{key: value for key, value in detail.items() if key != "kind"}))
                try:
                    return spec.run(args, context)
                finally:
                    progress.set_sink(None)
                    progress.set_event_sink(None)
            try:
                if tool in ("dv_build_graph", "dv_testplan"):
                    # Model stages have bounded API retries and durable checkpoints.
                    # Wait rather than leave a timed-out background writer.
                    outcome, value = "ok", invoke()
                else:
                    outcome, value = call_with_timeout(invoke, step["timeout_s"])
            except KeyboardInterrupt:
                step_records[step_id] = dict(status='INTERRUPTED', summary='Interrupted by user; successful responses and partial report preserved')
                emit('tool_interrupted',step=step_id,tool=tool,error_type='KeyboardInterrupt',
                     elapsed_s=round(time.monotonic()-tool_started,3))
                return finish('NEEDS_REVIEW',f"step {step_id!r} interrupted by user",pending=step_id,
                              approvals_needed=[step_id],question='Resume the same run to reuse completed responses; do not use --fresh.')
            if outcome == "timeout":
                result = dict(status="TIMEOUT",
                              summary=f"{tool} exceeded {step['timeout_s']}s",
                              files=[])
            else:
                result = value
        for produced in result.get("files", []):
            try:
                file_tags[str(Path(produced).resolve())] = spec.tag
            except OSError:
                file_tags[str(produced)] = spec.tag
        status = result.get("status", "FAIL")
        summary = result.get("summary", "")
        step_records[step_id] = dict(status=status, summary=summary)
        history.append(dict(step=step_id, tool=tool, status=status, summary=summary,
                            attempt=runs.get(step_id, 0),
                            revisit=revisits.get(step_id, 0),
                            extra_prompt=extra_prompt or None))
        emit("tool_done", step=step_id, status=status, summary=summary,
             elapsed_s=round(time.monotonic()-tool_started,3))
        if status == "PASS" and tool == "dv_testplan" and not dry_run:
            doc = next((f for f in result.get("files", [])
                        if f.endswith("testplan_doc.json")), None)
            post = guards.post_testplan_check(
                doc_path=Path(doc) if doc else out_dir / "missing_testplan_doc.json",
                rtl_used=bool((result.get("detail") or {}).get("rtl_used")
                              or args.get("rtl_graph")),
                expected_authority=args.get("source_authority"))
            if post:
                blocked_violations.extend(f"{step_id}: {v}" for v in post)
                emit("guard_block", step=step_id, violations=post)
                return finish(
                    "NEEDS_REVIEW",
                    f"strict never-do rule blocked step {step_id!r}: {post[0]}",
                    pending=step_id, approvals_needed=[step_id],
                    question="RTL observations must stay INFERRED and NEEDS_REVIEW. "
                             "Fix the plan output, then approve the step to run again.")
        if status in ("PASS", "NOT_RUN"):
            if not is_revisit:
                completed.add(step_id)
                index += 1
            else:
                pending_revisit = None
            if llm is None or dry_run or os.getenv("DV_AGENT_MODE", "basic") == "basic":
                continue
            next_step = order[index] if index < len(order) else None
            decision, decider_error = decider_mod.decide(
                llm, position=dict(completed=sorted(completed), index=index,
                                   tool_calls=tool_calls,
                                   overrides_used=overrides_used),
                history=history, next_step=({k: next_step[k] for k in
                                             ("id", "tool", "agent", "optional")
                                             } if next_step else None),
                budgets=dict(overrides_left=policy["max_overrides"] - overrides_used,
                             max_revisits_per_step=policy["max_revisits_per_step"],
                             max_extra_prompt_chars=policy["max_extra_prompt_chars"]),
                forbidden=flow["forbidden"])
            emit("decider", decision=decision, error=decider_error)
            problems = decider_mod.validate_decision(
                decision, steps=order, completed_ids=completed,
                next_step_id=next_step["id"] if next_step else None,
                revisits=revisits, overrides_used=overrides_used, policy=policy)
            if problems:
                invalid_decisions += 1
                emit("decider_rejected", problems=problems)
                if invalid_decisions > policy["max_overrides"]:
                    pending_id = next_step["id"] if next_step else step_id
                    return finish(
                        "NEEDS_REVIEW",
                        f"decider keeps proposing rejected actions "
                        f"({invalid_decisions}): {problems[0]}",
                        pending=pending_id, approvals_needed=[pending_id],
                        question="The decider repeatedly proposes actions outside "
                                 "the flow contract. Review the trace, then approve "
                                 "the pending step to resume with a fresh budget.")
                continue
            action = decision["action"]
            if action == "revisit":
                pending_revisit = (decision["target_step"].strip(),
                                   decision.get("extra_prompt", ""))
                overrides_used += 1
                emit("override", action="revisit", target=pending_revisit[0])
            elif action == "skip_optional" and next_step is not None:
                step_records[next_step["id"]] = dict(
                    status="SKIPPED",
                    summary=f"skipped by decider: {decision.get('reason', '')}")
                history.append(dict(step=next_step["id"], tool=next_step["tool"],
                                    status="SKIPPED",
                                    summary=decision.get("reason", "")))
                index += 1
                overrides_used += 1
                emit("override", action="skip_optional", target=next_step["id"])
            elif action == "stop":
                return finish(
                    "NEEDS_REVIEW",
                    f"decider stopped the run: {decision.get('reason', 'no reason')}",
                    pending=next_step["id"] if next_step else None,
                    approvals_needed=[next_step["id"]] if next_step else [],
                    question="The decider halted the flow. Review the trace, then "
                             "approve the pending step to resume.")
            continue
        if step.get("optional"):
            step_records[step_id] = dict(
                status="SKIPPED", summary=f"{status}: {summary}")
            history.append(dict(step=step_id, tool=tool, status="SKIPPED",
                                summary=f"{status}: {summary}"))
            emit("tool_skip_optional", step=step_id, status=status)
            if not is_revisit:
                index += 1
            else:
                pending_revisit = None
            continue
        if not is_revisit and runs[step_id] < step["max_attempts"]:
            emit("tool_retry", step=step_id, status=status, next_attempt=runs[step_id]+1,
                 recovery='Reuse successful response checkpoints; changed dependent context may need regeneration')
            continue
        return finish(
            "NEEDS_REVIEW",
            f"step {step_id!r} ended {status} after {runs.get(step_id, 0) + revisits.get(step_id, 0)} "
            f"execution(s): {summary}",
            pending=step_id, approvals_needed=[step_id],
            question=f"Step {step_id!r} did not pass. Fix the cause, then approve "
                     f"it to run again.")
    return finish("PASS", f"completed {len(order)} steps")
