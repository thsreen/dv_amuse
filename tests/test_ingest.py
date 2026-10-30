import hashlib

from dv_agent.ingest.ingest import ChunkConfig, _split_section, discover, find_headings, ingest


def test_discover_selects_spec_and_explains_skips(spec_repo):
    docs = {d.path: d for d in discover(spec_repo)}
    assert docs["doc/tmr32_spec.txt"].status == "INGESTED"
    assert "changelog" in docs["doc/CHANGES.txt"].reason
    assert "preferred format" in docs["doc/old/tmr32_spec.doc"].reason
    assert docs["README.md"].reason == "outside documentation directories"
    assert "rtl/notes.txt" not in docs


def test_include_glob_overrides_defaults(spec_repo):
    docs = {d.path: d.status for d in discover(spec_repo, include=["README.md"])}
    assert docs["README.md"] == "INGESTED"
    assert docs["doc/tmr32_spec.txt"] == "SKIPPED"


def test_headings_follow_numbering_and_ignore_table_rows():
    text = ("1\nIntro\nbody\n2 Regs\n2.1 Control (CTRL)\n0 RW Enable bit\n1 RW Other field\n"
            "2.2 Reload\n3 Interrupts\n2 bits otherwise\n")
    assert [(h.number, h.title) for h in find_headings(text, "text")] == [
        ("1", "Intro"), ("2", "Regs"), ("2.1", "Control (CTRL)"), ("2.2", "Reload"),
        ("3", "Interrupts")]


def test_markdown_headings():
    hs = find_headings("# Top\ntext\n## Child\nmore\n# Next\n", "markdown")
    assert [(h.number, h.title, h.depth) for h in hs] == [("1", "Top", 1), ("1.1", "Child", 2),
                                                         ("2", "Next", 1)]


def test_chunks_are_exact_slices_with_pages_and_no_running_headers(spec_repo, tmp_path):
    out = tmp_path / "run"
    manifest, chunks = ingest(spec_repo, out)
    doc = next(d for d in manifest.documents if d.status == "INGESTED")
    text = (out / doc.text_path).read_text(encoding="utf-8")
    assert "ACME TMR32 datasheet" not in text and "Confidential" not in text
    for c in chunks:
        assert text[c.char_start:c.char_end] == c.text
        assert hashlib.sha256(c.text.encode()).hexdigest() == c.text_sha256
    by_section = {c.section_path[-1]: c for c in chunks}
    assert by_section["2.2 Reload Register (RELOAD)"].page_start == 3
    assert by_section["2.1 Control Register (CTRL)"].section_path == [
        "2 Registers", "2.1 Control Register (CTRL)"]
    assert by_section["1 Introduction"].page_start == 2
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    _, again = ingest(spec_repo, tmp_path / "run2")
    assert [c.chunk_id for c in again] == [c.chunk_id for c in chunks]


def test_long_sections_split_on_paragraphs_contiguously():
    text = "\n\n".join(f"para {i} " + "x" * 300 for i in range(10))
    spans = _split_section(text, 0, len(text), ChunkConfig(max_chars=1000, min_chars=200))
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))
    assert all(e - s <= 1000 for s, e in spans)
    assert all(text[e - 2:e] == "\n\n" for _, e in spans[:-1])
