"""Deterministic subsection structure; no model calls or duplicated evidence."""


def entry_subsections(section, titles=None):
    titles = titles or {}
    groups = {}
    for index, entry in enumerate(section.get("entries", [])):
        key = entry.get("kind") or "general"
        # Keep implementation-derived coverage clearly separated.
        if section.get("id") == "coverage" and entry.get("cited_rtl_observation_ids"):
            key = "rtl_observation_coverage"
        if key not in groups:
            groups[key] = dict(id=key, heading=titles.get(key, key.replace("_", " ").title()),
                               entry_indexes=[], layout="table" if section.get("id") in ("checks", "coverage") else "bullets")
        groups[key]["entry_indexes"].append(index)
    ordered = [group for key, group in groups.items() if key != "rtl_observation_coverage"]
    if "rtl_observation_coverage" in groups:
        ordered.append(groups["rtl_observation_coverage"])
    return ordered


def organize_document(doc, template):
    """Store ordered headings and references to canonical content in the saved JSON."""
    presentation = template.get("presentation", {})
    titles = presentation.get("subsection_titles", {})
    doc["presentation"] = dict(section_heading_level=2, subsection_heading_level=3,
                               subsection_emphasis="bold", content_format="markdown",
                               grouping="entry kind; first occurrence order", **presentation)
    for index, section in enumerate(doc["sections"]):
        root = f"/sections/{index}"
        generator = section.get("generator")
        if generator == "entries":
            section["subsections"] = entry_subsections(section, titles)
            for subsection in section["subsections"]:
                subsection["content_path"] = root + "/entries"
        elif generator == "strategy":
            heading = titles.get("verification_approach", "Verification Approach")
            strategy = section.get("strategy") or {}
            strategy["subsection_heading"] = heading
            if strategy.get("overview"):
                section["subsections"] = [dict(id="verification_approach", heading=heading,
                                               content_path=root + "/strategy/overview", layout="bullets")]
            else:
                section["subsections"] = [dict(id=key, heading=label,
                                               content_path=root + "/strategy/" + key, layout="bullets")
                                          for key, label in (("agents", "Agents"), ("scoreboards", "Scoreboards"),
                                                             ("register_model", "Register model"),
                                                             ("virtual_sequences", "Virtual sequences"),
                                                             ("rtl_observation_actions", "RTL observations driving strategy"))
                                          if strategy.get(key)]
        elif generator == "register_map":
            section["subsections"] = [dict(id=f"register_{i}", heading=r["name"] or r["abbreviation"],
                                           content_path=f"/registers/registers/{i}", layout="expandable_row",
                                           detail_subsections=[dict(id="description", heading="Description", layout="paragraph",
                                                                    content_path=f"/registers/registers/{i}/description"),
                                                               dict(id="fields", heading="Fields", layout="table",
                                                                    content_path=f"/registers/registers/{i}/fields")])
                                      for i, r in enumerate((doc.get("registers") or {}).get("registers", []))]
        elif generator == "configurations":
            section["subsections"] = [dict(id="configuration_controls", heading="Configurable Register Controls",
                                           content_path=root + "/configurations", layout="table")]
        elif generator == "rtl_observations":
            section["subsections"] = [dict(id=e["id"], heading=f"{e['id']} — {e['kind']}",
                                           content_path=root + f"/entries/{i}", layout="bullets")
                                      for i, e in enumerate(section.get("entries", []))]
            section["collapsed"] = True
    if doc.get("interfaces"):
        doc["interfaces"]["subsections"] = [dict(id=f"interface_{i}", heading=g["name"],
                                                content_path=f"/interfaces/groups/{i}", layout="table")
                                           for i, g in enumerate(doc["interfaces"].get("groups", []))]
