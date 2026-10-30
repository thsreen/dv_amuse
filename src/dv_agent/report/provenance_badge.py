"""Compact, editable Markdown badges with HTML evidence tooltip metadata."""
import base64
import binascii
import json
import re


def badge(provenance: str, citations: list[str], reason: str = "", summary: str = "", where: str = "") -> str:
    citations = list(dict.fromkeys(c for c in citations if c))
    state = provenance if citations and provenance in ("DOCUMENTED", "INFERRED") else "NO_REFERENCE"
    icon = {"DOCUMENTED": "✅", "INFERRED": "⚠️", "NO_REFERENCE": "🛑"}[state]
    payload = dict(state=state, citations=citations,
                     reason=reason.strip() if state in ("DOCUMENTED", "INFERRED") else "")
    if summary:
        payload["summary"] = " ".join(summary.split())[:240]
    if where:
        payload["where"] = " | ".join(where.split(" | "))[:240]
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


def cite_marker(ids: list[str]) -> str:
    """Compact sources marker; renders as 📄 with excerpts on hover (see source_tip_summaries)."""
    ids = [i for i in dict.fromkeys(ids) if re.fullmatch(r"[A-Za-z0-9_-]+", i)]
    return f" 📄<!--dv-sources:{','.join(ids)}-->" if ids else ""


def decode_sources(payload: str) -> list[dict]:
    """Parse a dv-sources payload: enriched base64 JSON or a raw comma-separated ID list."""
    if len(payload) > 16384:
        raise ValueError("sources marker is too long")
    try:
        value = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, binascii.Error):
        value = None
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict) and re.fullmatch(r"[A-Za-z0-9_-]+", str(item.get("id", ""))):
                out.append({"id": item["id"], "where": str(item.get("where", ""))[:240],
                            "summary": str(item.get("summary", ""))[:1200]})
        if out:
            return out
        raise ValueError("invalid sources marker")
    ids = [i for i in dict.fromkeys(payload.split(",")) if re.fullmatch(r"[A-Za-z0-9_-]+", i)]
    if not ids:
        raise ValueError("invalid sources marker")
    return [{"id": i, "where": "", "summary": ""} for i in ids]


def source_tip_summaries(markdown: str, index: dict) -> str:
    """Embed compact source excerpts into each 📄 sources marker (idempotent)."""
    def replace(match):
        try:
            enriched = json.loads(base64.urlsafe_b64decode(match[1] + "=" * (-len(match[1]) % 4)))
            if isinstance(enriched, list):
                return match[0]  # already enriched
        except (ValueError, binascii.Error):
            pass
        try:
            ids = [s["id"] for s in decode_sources(match[1])]
        except ValueError:
            return match[0]
        if not ids:
            return match[0]
        payload = [{"id": i, "where": _place(index[i]) if i in index else "",
                    "summary": (" ".join((index[i].get("summary") or index[i].get("excerpt", "")).split())[:240]
                                if i in index else "")} for i in ids]
        encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode().rstrip("=")
        return f"📄<!--dv-sources:{encoded}-->"
    return re.sub(r"📄<!--dv-sources:([A-Za-z0-9_,-]+)-->", replace, markdown)


def _place(source: dict) -> str:
    where = source.get("path", "")
    if source.get("page") is not None:
        where += f", p.{source['page']}"
    if source.get("line_start") is not None:
        where += f":{source['line_start']}-{source.get('line_end', source['line_start'])}"
    return where


def source_summaries(markdown: str, index: dict) -> str:
    """Embed an exact, compact source excerpt into each existing evidence badge."""
    import re
    def replace(match):
        info = decode(match[1])
        summaries = [index[c].get("summary") or index[c].get("excerpt", "")
                     for c in info["citations"] if c in index]
        places = [_place(index[c]) for c in info["citations"] if c in index]
        return badge(info["state"], info["citations"], info["reason"],
                     info.get("summary", "") or " | ".join(summaries),
                     info.get("where", "") or " | ".join(dict.fromkeys(x for x in places if x)))
    return re.sub(r"(?:✅|⚠️|🛑)<!--dv-evidence:([A-Za-z0-9_-]+)-->", replace, markdown)
