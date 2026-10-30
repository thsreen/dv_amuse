"""Shared source-support policy, applied inside existing generation calls."""
from .extract import locate_quote

POLICY_VERSION = "source_support_v1"

PROVENANCE_RULES = """
Classify each atomic statement by source support, not by its section or writing style:
DOCUMENTED: explicitly stated OR an unambiguous factual restatement/normalization of cited source facts,
requiring no additional assumption. Examples: an input/output signal table defines DUT-relative directions;
a specified slave interface can be described as a responder; an explicit enable bit is a configuration control.
Exact wording need not match, but cite the supporting source. Do not mark these INFERRED merely because
you summarized, grouped, renamed a category, or translated a technical term.
INFERRED: adds an engineering choice, hypothesis, generalization or assumption beyond source facts.
Examples: choosing a UVM agent, a new sequence family, predictor architecture or random distribution
when the source does not prescribe it. Provide inference_reason describing that additional reasoning.
ASSUMED: no supplied evidence supports the statement. Never invent support or label plausibility DOCUMENTED.
Split factual behavior from proposed implementation when their statuses differ. Classify properties separately;
do not downgrade an entire interface or section because one property is inferred.
Unvalidated RTL-derived specifications and RTL observations remain INFERRED and require RTL engineer review;
this rule never promotes implementation evidence to approved intended behavior.
"""


def assessment_schema():
    return {"type": "object", "additionalProperties": False,
            "required": ["provenance", "quote", "chunk_id", "inference_reason"],
            "properties": {"provenance": {"type": "string", "enum": ["DOCUMENTED", "INFERRED", "ASSUMED"]},
                           "quote": {"type": "string"}, "chunk_id": {"type": "string"},
                           "inference_reason": {"type": "string"}}}


def assessment(raw, sources, fallback_ids=()):
    raw = raw or {}
    cid, quote = raw.get("chunk_id", ""), raw.get("quote", "").strip()
    loc = locate_quote(sources.get(cid, ""), quote) if len(quote) >= 8 else None
    cites = [cid] if loc else [c for c in fallback_ids if c in sources]
    state = raw.get("provenance", "INFERRED")
    if state not in ("DOCUMENTED", "INFERRED", "ASSUMED"):
        state = "ASSUMED"
    if state == "DOCUMENTED" and not loc:
        state = "INFERRED"
    if not cites:
        state = "ASSUMED"
    return dict(provenance=state, cited_chunk_ids=cites,
                quote=sources[cid][loc[0]:loc[1]] if loc else "",
                inference_reason=(raw.get("inference_reason", "").strip()
                                  or "Source support for this interpretation needs review.") if state == "INFERRED" else "")
