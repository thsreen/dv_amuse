"""Compact, editable Markdown badges with HTML evidence tooltip metadata."""
import base64
import json


def badge(provenance: str, citations: list[str], reason: str = "", summary: str = "") -> str:
    citations = list(dict.fromkeys(c for c in citations if c))
    state = provenance if citations and provenance in ("DOCUMENTED", "INFERRED") else "NO_REFERENCE"
    icon = {"DOCUMENTED": "✅", "INFERRED": "⚠️", "NO_REFERENCE": "🛑"}[state]
    payload = dict(state=state, citations=citations, reason=reason.strip() if state == "INFERRED" else "")
    if summary:
        payload["summary"] = " ".join(summary.split())[:240]
    encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode().rstrip("=")
    return f"{icon}<!--dv-evidence:{encoded}-->"


def decode(encoded: str) -> dict:
    if len(encoded) > 16384:
        raise ValueError("evidence badge is too long")
    value = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    if value.get("state") not in ("DOCUMENTED", "INFERRED", "NO_REFERENCE"):
        raise ValueError("unknown evidence state")
    if not isinstance(value.get("citations"), list) or not isinstance(value.get("reason"), str):
        raise ValueError("invalid evidence badge")
    return value


def source_summaries(markdown: str, index: dict) -> str:
    """Embed an exact, compact source excerpt into each existing evidence badge."""
    import re
    def replace(match):
        info = decode(match[1])
        summaries = [index[c].get("summary") or index[c].get("excerpt", "")
                     for c in info["citations"] if c in index]
        return badge(info["state"], info["citations"], info["reason"],
                     info.get("summary", "") or " | ".join(summaries))
    return re.sub(r"(?:✅|⚠️|🛑)<!--dv-evidence:([A-Za-z0-9_-]+)-->", replace, markdown)
