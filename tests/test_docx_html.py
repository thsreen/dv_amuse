import zipfile
from pathlib import Path

from dv_agent.ingest import discover, extract_document, ingest

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(text, style=None, page_break=False):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    brk = '<w:r><w:br w:type="page"/></w:r>' if page_break else ""
    return f"<w:p>{ppr}{brk}<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def _tbl(rows):
    cells = "".join("<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in row) + "</w:tr>" for row in rows)
    return f"<w:tbl>{cells}</w:tbl>"


def make_docx(path: Path, body: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>')
    return path


def _docx_spec(path):
    return make_docx(path, "".join([
        _p("Overview", "Heading1"),
        _p("The block counts pulses."),
        _p("Registers", "Heading1", page_break=True),
        _p("2.1 Control Register (CTRL)", "Heading2"),
        _tbl([["Bit", "Access", "Description"], ["0", "RW", "Enable"], ["7-1", "R", "Reserved"]]),
        _p("Reset Value: 00h"),
    ]))


def test_docx_headings_tables_and_pages(tmp_path):
    pages, mode = extract_document(_docx_spec(tmp_path / "spec.docx"), "docx")
    assert mode == "markdown" and len(pages) == 2
    assert pages[0].startswith("# Overview") and "The block counts pulses." in pages[0]
    assert "# Registers" in pages[1] and "## 2.1 Control Register (CTRL)" in pages[1]
    assert "0 | RW | Enable" in pages[1] and "Reset Value: 00h" in pages[1]


def test_docx_ingest_keeps_document_numbering_and_pages(tmp_path):
    repo = tmp_path / "repo"
    (repo / "doc").mkdir(parents=True)
    _docx_spec(repo / "doc" / "spec.docx")
    manifest, chunks = ingest(repo, tmp_path / "out")
    assert manifest.documents[0].status == "INGESTED" and manifest.documents[0].pages == 2
    paths = {" > ".join(c.section_path): c for c in chunks}
    assert "1 Overview" in paths
    ctrl = paths["2 Registers > 2.1 Control Register (CTRL)"]
    assert ctrl.page_start == 2 and "7-1 | R | Reserved" in ctrl.text


def test_html_headings_tables_and_skipped_markup(tmp_path):
    html = tmp_path / "spec.html"
    html.write_text("""<html><head><title>x</title><style>p{}</style></head><body>
      <h1>1 Overview</h1><p>The block&nbsp;counts <b>pulses</b>.<br>Second line.</p>
      <script>var hidden = 1;</script>
      <h2>1.1 Ports</h2>
      <table><tr><th>Port</th><th>Width</th><th>Direction</th></tr>
             <tr><td>CLK</td><td>1</td><td>Input</td></tr></table>
      <h1>2 Registers</h1><ul><li>CTRL &amp; STATUS</li></ul></body></html>""")
    pages, mode = extract_document(html, "html")
    text = pages[0]
    assert mode == "markdown" and len(pages) == 1
    assert "# 1 Overview" in text and "## 1.1 Ports" in text
    assert "The block counts pulses." in text and "Second line." in text
    assert "Port | Width | Direction" in text and "CLK | 1 | Input" in text
    assert "hidden" not in text and "p{}" not in text and "CTRL & STATUS" in text


def test_html_ingest_sections(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "spec.html").write_text("<h1>1 Intro</h1><p>Some intro text for the block.</p>"
                                             "<h2>1.1 Detail</h2><p>Detail text about the block behaviour.</p>")
    _, chunks = ingest(repo, tmp_path / "out")
    assert [c.section_path[-1] for c in chunks] == ["1 Intro", "1.1 Detail"]


def test_docx_and_html_are_now_supported_formats(tmp_path):
    repo = tmp_path / "repo"
    (repo / "doc").mkdir(parents=True)
    _docx_spec(repo / "doc" / "a.docx")
    (repo / "doc" / "b.html").write_text("<h1>1 B</h1><p>text</p>")
    status = {d.path: d.status for d in discover(repo)}
    assert status == {"doc/a.docx": "INGESTED", "doc/b.html": "INGESTED"}


def test_corrupt_docx_is_reported_not_fatal(tmp_path):
    repo = tmp_path / "repo"
    (repo / "doc").mkdir(parents=True)
    (repo / "doc" / "broken.docx").write_bytes(b"not a zip")
    (repo / "doc" / "ok.md").write_text("# 1 Ok\nbody text here\n")
    manifest, chunks = ingest(repo, tmp_path / "out")
    docs = {d.path: d for d in manifest.documents}
    assert docs["doc/broken.docx"].status == "FAILED" and "BadZipFile" in docs["doc/broken.docx"].reason
    assert chunks
