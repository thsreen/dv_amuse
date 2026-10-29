from html.parser import HTMLParser

from dv_agent.html_report import render_html
from dv_agent.provenance_badge import badge


class ReportText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.in_main = [], False
    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.in_main = True
    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = False
    def handle_data(self, data):
        if self.in_main and data.strip():
            self.parts.append(data.strip())


def test_html_preserves_report_content_and_formats_tables_and_lists():
    markdown = """# Peripheral plan

## Registers

| Name | Access | Description |
| --- | --- | --- |
| `CTRL` | RW | Mode \\| enable<br/>Reset: **0** |

- [INFERRED] Configure the mode
  - NEEDS_REVIEW

> Extraction incomplete; retained source rows.

_No simulation yet._
"""
    html = render_html(markdown)
    parser = ReportText()
    parser.feed(html)
    assert parser.parts == ["Peripheral plan", "Registers", "Name", "Access", "Description",
                            "CTRL", "RW", "Mode | enable", "Reset:", "0",
                            "[INFERRED] Configure the mode", "NEEDS_REVIEW",
                            "Extraction incomplete; retained source rows.", "No simulation yet."]
    assert "<table>" in html and "<ul>" in html and "<blockquote>" in html
    assert "<h2>Registers</h2>" in html and "<code>CTRL</code>" in html
    assert html.count('<script id="testplan-controls">') == 1
    assert '<script src=' not in html and '<link rel="stylesheet"' not in html


def test_html_escapes_source_html_and_disallows_active_links():
    md = '<script>alert("x")</script>\n\n[bad](javascript:alert) and [source](https://example.org/spec)\n'
    html = render_html(md)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert 'href="javascript:' not in html
    assert '<a href="https://example.org/spec">source</a>' in html


def test_fences_preserve_code_as_text():
    html = render_html("```sv\na <= b;\n```\n")
    assert "<pre><code>a &lt;= b;</code></pre>" in html


def test_evidence_badges_link_to_reference_and_explain_inference():
    reason = "A control dependency in the cited source motivates a directed test."
    md = ("## Findings\n\n"
          + "- " + badge("DOCUMENTED", ["REQ-1"]) + " Direct requirement\n"
          + "- " + badge("INFERRED", ["CH-2"], reason) + " Proposed test\n"
          + "- " + badge("ASSUMED", []) + " Unsupported claim\n\n"
          + "## Reference evidence\n\n### Reference REQ-1\n\nSource: spec.pdf, p.1\n\n"
          + "### Reference CH-2\n\nSource: spec.pdf, p.2\n")
    report = render_html(md)
    assert report.count('class="evidence-badge"') == 3
    assert 'aria-label="Documented"' in report and 'aria-label="Inferred"' in report
    assert 'aria-label="No verified reference"' in report
    assert 'href="#reference-REQ-1"' in report and 'href="#reference-CH-2"' in report
    assert 'id="reference-REQ-1"' in report and 'id="reference-CH-2"' in report
    assert "Reason: " + reason in report
    assert "🛑" in report and 'role="tooltip"' in report
