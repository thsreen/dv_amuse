"""Warning shown before `/code` builds anything, and the short window to stop it.

Code is generated only from DOCUMENTED plan items that cite a specification source, so `/code` starts
without a confirmation step. It says what will and will not be used, then waits a few seconds on a real
terminal for an abort command. Ctrl-C also stops it. Piped or scripted sessions do not wait.
"""
import os
import select
import sys

ABORT_WORDS = ("/abort", "abort", "/cancel", "cancel", "/stop", "stop")
DEFAULT_ABORT_SECONDS = 10.0
ABORT_SECONDS_ENV = "DV_AGENT_CODE_ABORT_SECONDS"


def count_plan_items(plan: dict) -> dict:
    """Classify plan entries the way code generation will: only cited DOCUMENTED items are used."""
    counts = dict(used=0, inferred=0, assumed=0, uncited_documented=0, rtl_observation=0, methodology=0,
                  total=0, with_requirement_ids=0)
    for section in plan.get("sections", []):
        for field in ("entries", "configurations"):
            for entry in section.get(field) or []:
                if not isinstance(entry, dict) or "provenance" not in entry:
                    continue
                counts["total"] += 1
                if entry.get("cited_rtl_observation_ids"):
                    counts["rtl_observation"] += 1
                elif entry.get("cited_methodology_ids") and not entry.get("cited_chunk_ids"):
                    counts["methodology"] += 1
                elif entry["provenance"] == "DOCUMENTED" and (entry.get("cited_chunk_ids") or entry.get("cited_req_ids")):
                    counts["used"] += 1
                    counts["with_requirement_ids"] += bool(entry.get("cited_req_ids"))
                elif entry["provenance"] == "DOCUMENTED":
                    counts["uncited_documented"] += 1
                elif entry["provenance"] == "INFERRED":
                    counts["inferred"] += 1
                else:
                    counts["assumed"] += 1
    return counts


def abort_seconds() -> float:
    try:
        return max(0.0, float(os.getenv(ABORT_SECONDS_ENV, DEFAULT_ABORT_SECONDS)))
    except ValueError:
        return DEFAULT_ABORT_SECONDS


def code_notice(plan: dict) -> list[str]:
    c = count_plan_items(plan)
    excluded = [f"{c[k]} {label}" for k, label in (("inferred", "inferred"), ("assumed", "assumed"),
                                                   ("uncited_documented", "documented without a citation"),
                                                   ("rtl_observation", "RTL observation")) if c[k]]
    lines = ["--- before code generation ---",
             f"Code is built only from the {c['used']} of {c['total']} plan entries that are DOCUMENTED and cite a "
             "specification source. The plan has not been signed off by a person; generated code stays NEEDS_REVIEW."]
    if excluded:
        lines.append("Not used: " + ", ".join(excluded) + ".")
    if c["methodology"]:
        lines.append(f"{c['methodology']} entr{'y comes' if c['methodology'] == 1 else 'ies come'} from DV-agent methodology rules "
                     "(\"Recommended by DV agent\"), not from the specification; they are not used as code facts.")
    if c["used"] and not c["with_requirement_ids"]:
        lines.append("Lineage: these entries cite source chunks only, with no requirement IDs (basic mode builds no requirement graph).")
    seconds = abort_seconds()
    lines.append(f"Type /abort and press Enter within {seconds:g} s, or press Ctrl-C at any time, to stop." if seconds
                 else "Press Ctrl-C at any time to stop.")
    return lines


def abort_requested(*, interactive: bool, seconds: float | None = None) -> bool:
    """Wait briefly on a real terminal for an abort command. Non-interactive sessions never wait."""
    seconds = abort_seconds() if seconds is None else seconds
    if not interactive or seconds <= 0 or not sys.stdin.isatty():
        return False
    try:
        ready, _, _ = select.select([sys.stdin], [], [], seconds)
    except (OSError, ValueError):  # no select() on this stdin (for example Windows)
        return False
    return bool(ready) and sys.stdin.readline().strip().lower() in ABORT_WORDS
