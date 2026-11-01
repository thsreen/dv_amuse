"""Deterministic interface base: which ports an interface owns, cited from the plan, with no model call.

The base of an interface is its port list (names, directions and widths from the interface JSON) plus the
specification evidence for those ports. The plan's interface step already extracted each signal with its verbatim
quote and chunk, so the evidence is attached, not re-derived. Asking a model to list the ports and also quote them
from a few retrieved excerpts failed repeatedly: it added context facts (a section heading, a protocol line) from
text it had not been shown, and the proof check refused them. Roles are not decided here; the next step assesses
what each interface needs.
"""
import json
from pathlib import Path

from .common_binding import _group_fact, _norm
from .contracts import Fact, safe_identifier

MAX_FACTS = 16


def _spec_to_rtl(directory):
    """Reviewed spec-name to RTL-port pairs from the port comparison, when a run has one."""
    path = Path(directory) / "interface_port_comparison.json"
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    from .port_validation import validated
    if not validated(report): return {}
    return {r["spec"]: r["rtl"] for r in report['rows'] if isinstance(r, dict) and r.get("status") == "PASS" and r.get("spec") and r.get("rtl")}


def _any_documented_fact(plan, sources):
    """Fallback citation: the first cited DOCUMENTED plan item, quoting the first line of its source."""
    from .reasoning import eligible_items
    for item in eligible_items(plan, sources):
        sid = item["source_ids"][0]
        quote = next((line.strip()[:160] for line in sources.get(sid, "").splitlines() if len(line.strip()) >= 8), "")
        if quote:
            return Fact(id="interface_basis", statement="Cited specification item", source_id=sid, quote=quote,
                        plan_pointer=item["plan_pointer"])
    return None



def _signal_facts(plan, ports, mapping):
    """One fact per owned port, from the plan signal that maps to it (reviewed mapping first, then exact name)."""
    wanted = {_norm(p): p for p in ports}
    facts, seen = [], set()
    for gi, group in enumerate((plan.get("interfaces") or {}).get("groups", [])):
        for si, signal in enumerate(group.get("signals", [])):
            port = mapping.get(signal.get("name")) or wanted.get(_norm(signal.get("name", "")))
            quote = (signal.get("quote") or "").strip()
            if port not in ports or port in seen or signal.get("provenance") != "DOCUMENTED" or not signal.get("chunk_id") or len(quote) < 8:
                continue
            seen.add(port)
            facts.append(Fact(id=safe_identifier("port_" + port), statement=f"The specification defines {signal['name']} as a port of this interface",
                              source_id=signal["chunk_id"], quote=quote, plan_pointer=f"/interfaces/groups/{gi}/signals/{si}"))
    return facts[:MAX_FACTS]


def interface_base(plan, task, sources, directory):
    """InterfaceBase for one inventory task: its ports and the documented evidence for them."""
    from .units import InterfaceBase
    ports = list(task.signals)
    if not ports or len(ports) != len(set(ports)):
        raise ValueError("Base interface must identify each scoped port exactly once")
    facts = _signal_facts(plan, set(ports), _spec_to_rtl(directory))
    if not facts:  # no signal evidence maps to these ports: cite the group, then any documented item
        groups = (plan.get("interfaces") or {}).get("groups", [])
        facts = [f for gi, g in enumerate(groups) if g.get("name") == task.id
                 and (f := _group_fact(plan, gi, g, "group_basis", "The specification defines this interface group"))]
    if not facts:
        fact = _any_documented_fact(plan, sources)
        facts = [fact] if fact else []
    if not facts:
        raise ValueError(f"No documented plan item can be cited for interface {task.id}")
    return InterfaceBase(ports=ports, roles={}, facts=facts, questions=[])
