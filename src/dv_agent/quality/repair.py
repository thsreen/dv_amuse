"""Refuse-and-repair: checks outside the model's control refuse a step's output with feedback and the
model repairs it, a bounded number of times.

The pipeline order stays fixed; this runs inside each step. `check(data)` returns the problems the
model can act on (an empty list accepts the output). Problems the specification itself causes (for
example two sources disagreeing) must not be returned by `check`: the model cannot repair them.
"""
import os
from dataclasses import dataclass, field
from typing import Callable

from ..core.llm import LLM, LLMError
from ..core.progress import emit
from ..core.trace import Tracer

REPAIR_INSTRUCTIONS = """
REPAIR: your previous answer (previous_output) was refused by the checks; the reasons are in refusal.
Return a complete corrected answer in the same format. Fix every listed problem and keep what was correct.
Never invent specification content to satisfy a check: if the specification does not support something,
remove it or mark it as not stated, unknown or ASSUMED where the format allows."""


def default_max_repairs() -> int:
    raw = os.getenv("DV_AGENT_MAX_REPAIRS", "2")
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"DV_AGENT_MAX_REPAIRS must be an integer, got {raw!r}") from None
    if value < 0:
        raise ValueError("DV_AGENT_MAX_REPAIRS must not be negative")
    return value


@dataclass
class RepairOutcome:
    data: dict
    attempts: int = 1
    history: list[dict] = field(default_factory=list)  # one entry per refusal: attempt and problems
    unresolved: list[str] = field(default_factory=list)  # problems left after the last attempt
    repair_error: str | None = None

    def summary(self) -> dict:
        return dict(attempts=self.attempts, refusals=self.history, unresolved=self.unresolved,
                    repair_error=self.repair_error)


def structured_with_repair(llm: LLM, tracer: Tracer, *, name: str, instructions: str, payload: dict,
                           schema: dict, check: Callable[[dict], list[str]],
                           max_repairs: int | None = None, _span_parent: str | None = None) -> RepairOutcome:
    """Call the model, then refuse and repair until the checks pass or the repair budget is spent.

    The first call's LLMError propagates (the step is BLOCKED); an error during a repair keeps the
    last answer and records the error.
    """
    budget = default_max_repairs() if max_repairs is None else max_repairs
    result = llm.structured(name=name, instructions=instructions, payload=payload, schema=schema, tracer=tracer,
                            _span_parent=_span_parent)
    outcome = RepairOutcome(data=result.data)
    problems = check(result.data)
    while problems and len(outcome.history) < budget:
        attempt = len(outcome.history) + 1
        outcome.history.append(dict(attempt=attempt, problems=problems))
        emit(f"{name}: checks refused the answer, repair attempt {attempt}/{budget} "
             f"({len(problems)} problems)")
        with tracer.span(f"refusal:{name}", input={"attempt": attempt, "problems": problems}, _parent=_span_parent) as span:
            try:
                result = llm.structured(
                    name=name, instructions=instructions + REPAIR_INSTRUCTIONS,
                    payload=payload | {"previous_output": outcome.data, "refusal": problems},
                    schema=schema, tracer=tracer, _span_parent=span.id)
            except LLMError as exc:
                outcome.repair_error = exc.kind
                span.update(level="ERROR", status_message=exc.kind)
                break
            outcome.data, outcome.attempts = result.data, outcome.attempts + 1
            problems = check(result.data)
            span.update(output={"remaining_problems": problems})
    outcome.unresolved = problems
    return outcome


def unresolved_questions(step: str, summary: dict | None, limit: int = 5) -> list[dict]:
    """Designer questions for problems that survived every repair attempt."""
    if not summary or not summary.get("unresolved"):
        return []
    problems = summary["unresolved"]
    shown = "; ".join(problems[:limit]) + (f"; and {len(problems) - limit} more" if len(problems) > limit else "")
    return [dict(text=f"The {step} step could not be completed from the specification after "
                      f"{len(summary['refusals'])} repair attempt(s): {shown}. Please clarify.",
                 kind="question", provenance="INFERRED", cited_req_ids=[], cited_chunk_ids=[],
                 details=["Raised by refuse-and-repair"], validation=[])]


def render_repairs(summary: dict | None) -> list[str]:
    if not summary or not summary.get("refusals"):
        return []
    lines = []
    for r in summary["refusals"]:
        lines.append(f"> Refused (attempt {r['attempt']}): " + "; ".join(r["problems"]))
    if summary.get("unresolved"):
        lines.append(f"> Still unresolved after repair: {'; '.join(summary['unresolved'])}")
    else:
        lines.append(f"> Repaired after {len(summary['refusals'])} refusal(s).")
    if summary.get("repair_error"):
        lines.append(f"> Repair stopped: model call failed ({summary['repair_error']}).")
    return lines + [""]
