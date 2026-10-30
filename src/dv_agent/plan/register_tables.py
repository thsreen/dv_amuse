"""Conservative register inventory from explicit specification tables.

This handles Name/Address/Width/Access/Description tables, including PDF text
with wrapped register names. Other layouts remain the model extractor's job.
Every emitted attribute and quote is copied from the original source text.
"""
import re


_HEADER = re.compile(r"^\s*\|?\s*Name\s*[| ]+\s*(?:Address|Offset)\s*[| ]+\s*Width\s*[| ]+\s*Access\b", re.I)
_NUMBER = r"(?:0x[0-9a-fA-F]+|[0-9a-fA-F]+[hH]|[0-9]+)"
_ROW = re.compile(
    rf"^(?P<name>.*?)\s*(?<!\S)(?P<address>{_NUMBER})\s+(?P<width>\d+)\s+"
    r"(?P<access>R/W|RW|RO|WO|W1C|W1S|R|W)\b\s*(?P<description>.*)$", re.I)


def table_records(chunk: dict) -> list[dict]:
    """Return raw extractor records; no assumptions about access conditions or reset."""
    lines = chunk["text"].splitlines()
    records = []
    active = False
    pending: list[str] = []
    for raw in lines:
        if _HEADER.search(raw):
            active, pending = True, []
            continue
        if not active:
            continue
        if not raw.strip():
            active, pending = False, []
            continue
        text = raw.strip().strip("|").replace("|", " ").strip()
        if re.fullmatch(r"[-: ]+", text):  # Markdown separator
            continue
        match = _ROW.fullmatch(text)
        if not match:
            pending.append(raw)
            continue
        row = match.groupdict()
        # Prefix-only lines are a wrapped name when the numeric row has no name.
        # Never attach preceding descriptions to a row that already has a name.
        prefix = pending if not row["name"].strip() else []
        name = " ".join([p.strip() for p in prefix] + [row["name"].strip()]).strip()
        pending = []
        if not name or len(name) > 200:
            continue
        abbreviation = re.search(r"\(([A-Z][A-Z0-9_]*)\)", name)
        records.append(dict(name=name, abbreviation=abbreviation.group(1) if abbreviation else "",
                            address=row["address"], width=row["width"], access=row["access"],
                            reset_value="", description=row["description"], availability="",
                            quote="\n".join(prefix + [raw]), chunk_id=chunk["chunk_id"], fields=[]))
    return records
