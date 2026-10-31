"""DV-agent methodology rules: natural-language conditions without a spec source.

Entries backed only by a methodology rule are DOCUMENTED with reason
'Recommended by DV agent' and cite the rule ID (``METH-...``). Enforced
rules are force-injected into their sections even when the model omits
them. Users extend or override the shipped defaults with their own JSON
file (``--methodology-rules``); same ID replaces the shipped rule.
"""

import hashlib
import json
import re
from pathlib import Path

RECOMMENDED_REASON = "Recommended by DV agent"

RULE_ID_RE = re.compile(r"^METH-[A-Z0-9][A-Z0-9-]*$")
MAX_STATEMENT = 4000
MAX_RULES = 64

TEMPLATE_FILENAME = "methodology_rules_v0.json"
PIN_FILENAME = TEMPLATE_FILENAME + ".sha256"


class ProtectedFileChanged(ValueError):
    """The shipped rules differ from the owner's pinned digest."""


def default_rules_path() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / TEMPLATE_FILENAME


def shipped_rules_bytes() -> bytes:
    """The shipped rules file, verified against the owner's pinned SHA-256 before anything uses it.

    These rules become plan entries tagged "Recommended by DV agent", so an agent must never be able to
    change them unnoticed. The pin sits beside the file and both are write-protected for agents
    (docs/PROTECTED_FILES.md). A mismatch is an error, not a warning.
    """
    path = default_rules_path()
    data = path.read_bytes()
    pin = path.with_name(PIN_FILENAME)
    try:
        expected = pin.read_text(encoding="utf-8").split()[0].lower()
    except (OSError, IndexError):
        raise ProtectedFileChanged(f"{TEMPLATE_FILENAME}: pin file {PIN_FILENAME} is missing or empty") from None
    if hashlib.sha256(data).hexdigest() != expected:
        raise ProtectedFileChanged(
            f"{TEMPLATE_FILENAME} does not match its owner-pinned SHA-256. Only the owner may change it: review the "
            f"diff, then re-pin with `sha256sum {TEMPLATE_FILENAME} > {PIN_FILENAME}` (docs/PROTECTED_FILES.md).")
    return data


def _rule_error(source: str, index: int, problem: str) -> ValueError:
    return ValueError(f"methodology rules {source}: rule #{index}: {problem}")


def validate_rules(raw: object, source: str) -> list[dict]:
    """Validate a decoded rules file; return normalized rule dicts."""
    if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
        raise ValueError(f"methodology rules {source}: need "
                         f'{{"rules": [...]}}')
    rules = raw["rules"]
    if len(rules) > MAX_RULES:
        raise ValueError(f"methodology rules {source}: more than "
                         f"{MAX_RULES} rules")
    seen: set[str] = set()
    out = []
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise _rule_error(source, i, "not an object")
        rid = rule.get("id", "")
        if not isinstance(rid, str) or not RULE_ID_RE.match(rid):
            raise _rule_error(source, i, "id must match METH-... "
                             "(uppercase, digits, dashes)")
        if rid in seen:
            raise _rule_error(source, i, f"duplicate id {rid}")
        seen.add(rid)
        statement = rule.get("statement", "")
        if not isinstance(statement, str) or len(statement.strip()) < 20:
            raise _rule_error(source, i, "statement needs at least 20 "
                             "characters of natural language")
        if len(statement) > MAX_STATEMENT:
            raise _rule_error(source, i, f"statement over {MAX_STATEMENT} "
                             "characters")
        applies_to = rule.get("applies_to", [])
        if (not isinstance(applies_to, list) or not applies_to
                or not all(isinstance(s, str) and s.strip()
                           for s in applies_to)):
            raise _rule_error(source, i, "applies_to needs a non-empty "
                             "list of section ids")
        kinds = rule.get("kinds", [])
        if (not isinstance(kinds, list) or not kinds
                or not all(isinstance(s, str) and s.strip()
                           for s in kinds)):
            raise _rule_error(source, i, "kinds needs a non-empty list "
                             "of entry kinds")
        enforced = rule.get("enforced", False)
        if not isinstance(enforced, bool):
            raise _rule_error(source, i, "enforced must be true/false")
        check_text = rule.get("check_text", "") or statement.strip()
        if not isinstance(check_text, str) or len(check_text.strip()) < 20:
            raise _rule_error(source, i, "check_text needs at least 20 "
                             "characters")
        rationale = rule.get("rationale", "")
        if not isinstance(rationale, str):
            raise _rule_error(source, i, "rationale must be a string")
        out.append({"id": rid, "statement": statement.strip(),
                    "applies_to": [s.strip() for s in applies_to],
                    "kinds": [s.strip() for s in kinds],
                    "enforced": enforced, "check_text": check_text.strip(),
                    "rationale": rationale.strip()})
    return out


def load_methodology_rules(path: str | Path | None = None) -> list[dict]:
    """Load shipped defaults merged with an optional user file.

    User rules with the same ID replace shipped rules; new IDs are
    appended. Raises ValueError on unreadable or invalid files.
    """
    defaults = validate_rules(json.loads(shipped_rules_bytes().decode("utf-8")), "defaults")
    if path in (None, ""):
        return defaults
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"methodology rules {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"methodology rules {path}: invalid JSON "
                         f"({exc})") from exc
    user_rules = validate_rules(raw, str(path))
    merged = {rule["id"]: rule for rule in defaults}
    merged.update({rule["id"]: rule for rule in user_rules})
    return [merged[rule["id"]] for rule in defaults
            if rule["id"] in merged] + [
                rule for rule in user_rules
                if rule["id"] not in {r["id"] for r in defaults}]


def rules_fingerprint(rules: list[dict]) -> str:
    """Stable short hash of the effective rule set for cache-busting."""
    canonical = json.dumps(rules, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def rules_for_section(rules: list[dict], section_id: str) -> list[dict]:
    return [rule for rule in rules if section_id in rule["applies_to"]]


def missing_enforced(entries: list[dict], rules: list[dict],
                     section_id: str) -> list[str]:
    """IDs of enforced rules for this section that no entry cites yet."""
    cited: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict):
            cited.update(i for i in
                         entry.get("cited_methodology_ids", []) or []
                         if isinstance(i, str))
    return [rule["id"] for rule in rules_for_section(rules, section_id)
            if rule["enforced"] and rule["id"] not in cited]


def forced_entry(rule: dict) -> dict:
    """Deterministic plan entry for an enforced methodology rule."""
    return {
        "text": rule["check_text"],
        "kind": rule["kinds"][0],
        "details": [f"{RECOMMENDED_REASON} ({rule['id']})."]
        + ([rule["rationale"]] if rule["rationale"] else []),
        "cited_req_ids": [],
        "cited_chunk_ids": [],
        "cited_methodology_ids": [rule["id"]],
        "provenance": "DOCUMENTED",
        "inference_reason": RECOMMENDED_REASON,
        "quote": rule["statement"][:240],
        "validation": [],
        "status": "NOT_RUN",
    }
