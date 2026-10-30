"""Token usage per run and per model call, read from the run's trace.

Each model call is a `generation` span in trace.jsonl carrying its usage as reported by the Meta Model
API (input, output, reasoning and cached-input tokens) and whether the response came from the local
response cache. When the API reports no usage, the call is estimated at about 4 characters per token
and counted in `estimated_calls`.

Two kinds of caching are kept apart:
- cached_input: input tokens the provider served from its prompt cache (part of `input`).
- local cache hits: calls answered from llm_cache/ with no API call; they consume nothing in this run
  and are reported under `replayed` (what they used when first made).
"""
import json
from pathlib import Path

from .trace import read_trace

TOKEN_KEYS = ("input", "cached_input", "output", "reasoning")
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def estimate_usage(instructions: str, payload: dict, schema: dict, output: dict) -> dict:
    """Rough usage for a call whose response reported none."""
    prompt = instructions + json.dumps(payload, ensure_ascii=False) + json.dumps(schema)
    return dict(input=estimate_tokens(prompt), cached_input=0,
                output=estimate_tokens(json.dumps(output, ensure_ascii=False)), reasoning=0)


def _tokens() -> dict:
    return {k: 0 for k in TOKEN_KEYS}


def _finish(t: dict) -> dict:
    """Add derived counts: uncached input and total (input + output; reasoning is part of output)."""
    return dict(t, uncached_input=t["input"] - min(t["cached_input"], t["input"]), total=t["input"] + t["output"])


def _blank() -> dict:
    return dict(calls=0, api_calls=0, local_cache_hits=0, repair_calls=0, estimated_calls=0,
                consumed=_tokens(), replayed=_tokens())


def _add(acc: dict, usage: dict, cached: bool, estimated: bool, repair: bool, api_attempts: int = 1) -> None:
    acc["calls"] += 1
    acc["local_cache_hits" if cached else "api_calls"] += 1 if cached else api_attempts
    acc["repair_calls"] += repair
    acc["estimated_calls"] += estimated
    bucket = acc["replayed" if cached else "consumed"]
    for k in TOKEN_KEYS:
        bucket[k] += int(usage.get(k, 0) or 0)


def _final(acc: dict) -> dict:
    return dict(acc, consumed=_finish(acc["consumed"]), replayed=_finish(acc["replayed"]),
                from_scratch=_finish({k: acc["consumed"][k] + acc["replayed"][k] for k in TOKEN_KEYS}))


def summarize(sink: Path, trace_ids: str | list[str] | None = None) -> dict:
    """Token totals per run (trace) and per model-call name, plus overall totals."""
    wanted = [trace_ids] if isinstance(trace_ids, str) else trace_ids
    records = [r for r in read_trace(sink) if wanted is None or r["trace_id"] in wanted]
    roots = {r["trace_id"]: r for r in records if r.get("parent_id") is None}
    span_names = {r["span_id"]: r["name"] for r in records}
    runs: dict[str, dict] = {}
    total, by_call_all = _blank(), {}
    for r in records:
        if r.get("type") != "generation":
            continue
        meta = r.get("metadata", {})
        usage, cached, estimated = r.get("usage") or {}, bool(meta.get("cached")), bool(meta.get("usage_estimated"))
        name = r["name"].removeprefix("llm:")
        repair = span_names.get(r.get("parent_id"), "").startswith("refusal:")
        run = runs.setdefault(r["trace_id"], dict(totals=_blank(), by_call={}))
        for acc in (run["totals"], run["by_call"].setdefault(name, _blank()), total, by_call_all.setdefault(name, _blank())):
            _add(acc, usage, cached, estimated, repair, len(meta.get("api_attempts") or [None]))
    out_runs = [dict(trace_id=tid, run=roots.get(tid, {}).get("name"), started_utc=roots.get(tid, {}).get("start_utc"),
                     model=(roots.get(tid, {}).get("metadata") or {}).get("model"), totals=_final(run["totals"]),
                     by_call={k: _final(v) for k, v in sorted(run["by_call"].items())})
                for tid, run in runs.items()]
    out_runs.sort(key=lambda r: r["started_utc"] or "")
    return dict(runs=out_runs, totals=_final(total), by_call={k: _final(v) for k, v in sorted(by_call_all.items())})


def run_totals(sink: Path, trace_ids: str | list[str]) -> dict:
    """Compact totals for command output."""
    t = summarize(sink, trace_ids)["totals"]
    return {k: t[k] for k in ("calls", "api_calls", "local_cache_hits", "repair_calls", "estimated_calls",
                              "consumed", "from_scratch")}


def render(usage: dict, heading: str = "Token usage") -> list[str]:
    """Markdown table per model call for the final document."""
    lines = [f"## {heading}", "",
             "Tokens consumed from the Meta Model API in the runs that produced this document. Cached input is "
             "served from the provider's prompt cache (part of input); reasoning is part of output. Calls answered "
             "from the local response cache consumed nothing in this run; their original usage is listed as replayed.",
             ""]
    for label, part in usage.items():
        if not part or not part["totals"]["calls"]:
            continue
        lines += [f"### {label}", "",
                  "| Model call | Calls (API / local cache) | Repairs | Input | Cached input | Uncached input | Output | Reasoning | Total |",
                  "|---|---|---|---|---|---|---|---|---|"]
        rows = list(part["by_call"].items()) + [("**Total**", part["totals"])]
        for name, acc in rows:
            c = acc["consumed"]
            lines.append(f"| {name} | {acc['calls']} ({acc['api_calls']} / {acc['local_cache_hits']}) | "
                         f"{acc['repair_calls']} | {c['input']} | "
                         f"{c['cached_input']} | {c['uncached_input']} | {c['output']} | {c['reasoning']} | {c['total']} |")
        t = part["totals"]
        lines.append("")
        if t["local_cache_hits"]:
            r = t["replayed"]
            lines.append(f"Replayed from the local cache: {t['local_cache_hits']} calls, {r['input']} input and "
                         f"{r['output']} output tokens. From scratch: {t['from_scratch']['total']} tokens.")
        if t["repair_calls"]:
            lines.append(f"{t['repair_calls']} of {t['calls']} calls were repairs after a check refused the model's answer.")
        if t["estimated_calls"]:
            lines.append(f"{t['estimated_calls']} call(s) reported no usage and are estimated at about "
                         f"{CHARS_PER_TOKEN} characters per token.")
        lines.append("")
    return lines
