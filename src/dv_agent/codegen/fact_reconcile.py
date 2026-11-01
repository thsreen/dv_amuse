"""Keep what a model chose; replace the evidence it could not prove.

A model answer has two parts: a decision (which agent, which ties, which role) and the facts it cites for it. The
decision is the model's work. The proof is checked in code: the cited plan item must have been retrieved and the quote
must occur in a retrieved excerpt. When a cited fact fails that check, refusing the whole answer cost two calls and
blocked the run, while the decision was usually fine. Instead the unprovable facts are dropped, every reference to
them is re-pointed to proven facts (the interface's own documented facts when nothing else remains), and the
substitution is written into the unit's questions so a reviewer sees it. Nothing unproven is ever kept.
"""
from pydantic import BaseModel


def _references(node, found):
    """Every object that carries `fact_ids`, anywhere inside a validated model."""
    if isinstance(node, BaseModel):
        if hasattr(node, "fact_ids"):
            found.append(node)
        for name in type(node).model_fields:
            _references(getattr(node, name), found)
    elif isinstance(node, (list, tuple)):
        for child in node:
            _references(child, found)


def reconcile_facts(unit, provable, fallback=()):
    """Drop facts `provable` rejects, re-point references, and note it. Returns the dropped fact ids.

    provable(fact) raises ValueError when a fact cannot be proven. fallback: proven facts to fall back on.
    """
    kept, dropped = [], {}
    for fact in unit.facts:
        try:
            provable(fact)
            kept.append(fact)
        except ValueError as exc:
            dropped[fact.id] = str(exc)
    if not dropped:
        return []
    substitute = kept or list(fallback)
    if not substitute:
        raise ValueError("No cited fact can be proven from the retrieved evidence: " + "; ".join(sorted(set(dropped.values()))))
    unit.facts[:] = kept or list(fallback)
    replacement = [f.id for f in substitute]
    references = []
    _references(unit, references)
    for item in references:
        item.fact_ids = [x for x in item.fact_ids if x not in dropped] or list(replacement)
    if hasattr(unit, "questions"):
        unit.questions.append("Evidence substituted: " + ", ".join(sorted(dropped)) +
                              " could not be proven from the retrieved sources (" + "; ".join(sorted(set(dropped.values()))) +
                              "); the documented facts of this interface are cited instead. Review the choice that cited them.")
    return sorted(dropped)


def rename_conflicting_facts(unit, known):
    """Give a unit's fact a new id when an earlier unit already uses that id for a different fact.

    Fact ids are labels each model call picks on its own, so two units can both call a different fact `f_source`. The
    contract needs one fact per id: identical facts merge, different ones are renamed here (references in the unit
    follow) instead of stopping the run. known: {fact id: fact dict} of what is already in the plan. Returns {old: new}.
    """
    taken = set(known) | {f.id for f in unit.facts}
    renamed = {}
    for fact in unit.facts:
        if fact.id in known and known[fact.id] != fact.model_dump():
            number = 2
            while f"{fact.id}_{number}" in taken:
                number += 1
            renamed[fact.id] = new = f"{fact.id}_{number}"
            taken.add(new)
            fact.id = new
    if renamed:
        references = []
        _references(unit, references)
        for item in references:
            item.fact_ids = [renamed.get(x, x) for x in item.fact_ids]
    return renamed


def _fact_key(fact):
    return (fact["source_id"], fact["quote"], fact["plan_pointer"]) if isinstance(fact, dict) else (fact.source_id, fact.quote, fact.plan_pointer)


def reuse_existing_facts(unit, known):
    """A fact is its evidence: the same source, quote and plan item already in the plan is reused, not added under a new id.

    Each model answer restates the facts it cites, so a long run outgrows the contract's fact limit with copies.
    known: {fact id: fact dict}. References in the unit follow. Returns {dropped id: reused id}.
    """
    by_evidence = {_fact_key(fact): fact_id for fact_id, fact in known.items()}
    reused, kept = {}, []
    for fact in unit.facts:
        existing = by_evidence.get(_fact_key(fact))
        if existing is None:
            by_evidence[_fact_key(fact)] = fact.id
            kept.append(fact)
        elif existing != fact.id:
            reused[fact.id] = existing
        elif fact.id not in known:
            kept.append(fact)
    unit.facts[:] = kept
    if reused:
        references = []
        _references(unit, references)
        for item in references:
            item.fact_ids = list(dict.fromkeys(reused.get(x, x) for x in item.fact_ids))
    return reused


def drop_unreferenced_facts(unit):
    """Facts only a deferred item cited need not enter the plan."""
    references = []
    _references(unit, references)
    used = {x for item in references for x in item.fact_ids}
    unit.facts[:] = [fact for fact in unit.facts if fact.id in used]
