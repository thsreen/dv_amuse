"""Explicit, precondition-first dependencies for test-plan generation."""

REQUIRED_FOUNDATIONS = ["@registers", "feature_description", "register_map"]


def validate_dependencies(sections: list[dict]) -> None:
    seen = {"@interfaces", "@registers"}
    for section in sections:
        dependencies = section.get("depends_on", [])
        if not isinstance(dependencies, list) or any(not isinstance(x, str) for x in dependencies):
            raise ValueError(f"section {section['id']}: depends_on must be a list of IDs")
        unknown = set(dependencies) - seen
        if unknown:
            raise ValueError(f"section {section['id']}: dependencies must precede it: {sorted(unknown)}")
        seen.add(section["id"])


def dependency_state(section: dict, sections: list[dict], interfaces: dict | None,
                     registers: dict | None) -> list[dict]:
    available = {s["id"]: s for s in sections}
    available.update({"@interfaces": interfaces, "@registers": registers})
    names = list(section.get("depends_on", []))
    # These are absolute gates, independent of template order or optional settings.
    names.append("@registers")
    if section.get("generator") != "title" and section["id"] != "feature_description":
        names.append("feature_description")
        if section.get("generator") != "register_map":
            names.append("register_map")
    # Sequential execution is mandatory, including custom templates and diagnostics.
    # Extraction steps precede the first document section.
    previous = ([sections[-1]["id"]] if sections else
                [name for name, item in (("@interfaces", interfaces), ("@registers", registers)) if item is not None])
    names = list(dict.fromkeys(names + previous))
    result = []
    for name in names:
        item = available.get(name)
        status = item.get("status", "NOT_RUN") if item else "NOT_RUN"
        # A successfully inspected design without registers needs no register configuration.
        optional = (item is not None and item.get("generator") == "configurations"
                    and status == "NOT_RUN" and registers is not None
                    and registers.get("status") == "PASS" and not registers.get("registers"))
        optional = optional or (item is not None and item.get("generator") == "rtl_observations"
                                and status == "NOT_RUN" and not item.get("blocked_by"))
        result.append(dict(id=name, status=status, satisfied=status == "PASS" or optional,
                           reason=(item or {}).get("error") or
                           "; ".join(str(x) for x in (item or {}).get("validation", [])[:3]) or
                           ("" if status == "PASS" else "Prerequisite is unavailable or incomplete")))
    return result


def document_status(doc: dict) -> dict:
    """Readiness is separate from completion and human review/sign-off."""
    blockers = []
    for name in ("interfaces", "registers"):
        item = doc.get(name)
        if (name == "registers" and (item or {}).get("status") != "PASS") or (
                item and item.get("status") not in ("PASS", "NOT_RUN")):
            blockers.append(dict(id="@" + name, status=(item or {}).get("status", "NOT_RUN")))
    present = {s["id"] for s in doc.get("sections", [])}
    for required in REQUIRED_FOUNDATIONS[1:]:
        if required not in present:
            blockers.append(dict(id=required, status="NOT_RUN"))
    for section in doc.get("sections", []):
        optional = section.get("generator") == "rtl_observations" and section.get("status") == "NOT_RUN"
        no_registers = (section.get("generator") == "configurations" and
                        (doc.get("registers") or {}).get("status") == "PASS" and
                        not (doc.get("registers") or {}).get("registers"))
        if section.get("status") != "PASS" and not optional and not (no_registers and section.get("status") == "NOT_RUN"):
            blockers.append(dict(id=section["id"], status=section.get("status", "NOT_RUN"),
                                 blocked_by=section.get("blocked_by", [])))
    progress = doc.get("generation_status")
    status = ("IN_PROGRESS" if progress == "IN_PROGRESS" else
              "BLOCKED" if blockers or progress in ("INTERRUPTED", "ERROR") else "PASS")
    return dict(status=status, blocking_dependencies=blockers)
