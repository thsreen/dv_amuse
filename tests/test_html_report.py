from html.parser import HTMLParser

import pytest

from dv_agent.report.html_report import render_html
from dv_agent.report.provenance_badge import badge


class ReportText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.in_main, self.chrome = [], False, []
    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.in_main = True
        classes = (dict(attrs).get("class") or "").split()
        if self.chrome or (self.in_main and ("toc" in classes or "legend" in classes)):
            self.chrome.append(tag)  # contents bar and legend are navigation chrome, not report text
    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = False
        if self.chrome and tag == self.chrome[-1]:
            self.chrome.pop()
    def handle_data(self, data):
        if self.in_main and not self.chrome and data.strip():
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


def test_collapsed_spec_quotes_preserve_content_and_escape_html():
    md = ('<details>\n<summary>Specification evidence</summary>\n\n'
          '> Input CLK is the clock. <script>unsafe()</script>\n\n</details>')
    report = render_html(md)
    assert '<details class="source-quotes">' in report
    assert '<blockquote>' in report and 'Input CLK is the clock.' in report
    assert '&lt;script&gt;unsafe()&lt;/script&gt;' in report
    assert '<script>unsafe()' not in report


def test_collapsed_interface_info_renders_bullets_and_badges():
    info = badge("DOCUMENTED", ["CH-1"])
    directions = badge("INFERRED", ["CH-1"], "one direction is unstated in the source")
    md = ('<details>\n<summary>ⓘ Interface info</summary>\n\n'
          f'- Function: WISHBONE SoC bus interface for register access {info}\n'
          f'- Signal directions: both directions {directions}\n\n</details>')
    report = render_html(md)
    assert '<details class="interface-info"><summary>ⓘ Interface info</summary>' in report
    assert '<details class="interface-info" open' not in report
    block = report.split('<details class="interface-info">')[1].split('</details>')[0]
    assert "<ul>" in block and "Function: WISHBONE" in block
    assert block.count('class="evidence-badge"') == 2


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


def test_source_tooltip_has_single_line_excerpt_and_reference_link():
    from dv_agent.report.provenance_badge import source_summaries
    md = "- " + badge("DOCUMENTED", ["CH-signal"])
    md = source_summaries(md, {"CH-signal": {"excerpt": "RESET is active low.\n<script>bad</script>"}})
    report = render_html(md)
    assert 'Source excerpt: RESET is active low. &lt;script&gt;bad&lt;/script&gt;' in report
    assert 'href="#reference-CH-signal"' in report
    assert '<script>bad</script>' not in report


def test_register_details_are_inserted_as_hidden_subtable_rows():
    md = ('| Register | Address |\n| --- | --- |\n'
          '| CTRL<!--dv-register:0123456789abcdef--> | 0x00 |\n\n'
          '<!--dv-register-detail:0123456789abcdef-->\n'
          'Description: Control register.\n\n'
          '| Field | Description |\n| --- | --- |\n| EN | Enable |\n\n'
          '<!--dv-register-detail-end-->')
    report = render_html(md)
    assert '<tr data-register-row="0123456789abcdef">' in report
    assert 'aria-expanded="false"' in report and 'aria-controls="register-detail-0123456789abcdef"' in report
    assert '<tr id="register-detail-0123456789abcdef" class="register-detail-row" hidden><td colspan="2">' in report
    assert 'Description: Control register.' in report and '<td>EN</td>' in report
    assert '<section data-register-detail=' not in report


def test_rtl_observations_are_collapsed_under_the_section_heading():
    from dv_agent.plan.rtl_observations import render
    result = dict(status="PASS", entries=[dict(id="OBS-1", kind="reset", text="Review reset handling.",
                  cited_rtl_excerpt_ids=["SRC-1"], inference_reason="RTL reset path needs review.",
                  suggested_verification="Exercise reset during traffic.", spec_relationship="Unconfirmed gap.",
                  designer_question="Confirm reset sequencing.")],
                  evidence=[dict(id="SRC-1", path="block.sv", line_start=3, line_end=8)])
    md = '\n'.join(render(result, "4. Observations from RTL"))
    report = render_html(md)
    assert '<details class="rtl-observations"><summary><h2>4. Observations from RTL</h2></summary>' in report
    assert '<details class="rtl-observations" open' not in report
    assert '<strong>Proposed test:</strong>' in report and '<strong>Designer question:</strong>' in report
    assert '<h3>OBS-1' in report and 'RTL design engineer review required' in report
    assert md.index('## 4. Observations') < md.index('### OBS-1')


def test_blocked_rtl_section_still_has_an_expandable_header():
    from dv_agent.plan.rtl_observations import render
    report = render_html('\n'.join(render(dict(status="BLOCKED", error="No graph available."), "RTL Observations")))
    assert '<details class="rtl-observations">' in report
    assert '<strong>BLOCKED</strong>: No graph available.' in report


def test_register_accordion_clicks_and_exclusive_expansion():
    import shutil
    import subprocess
    import pytest
    from dv_agent.report.html_report import _REGISTER_SCRIPT
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    harness = r'''
const assert = require('node:assert/strict');
let click;
const details = {};
function makeRow(id) {
  details[id] = {hidden: true};
  const attrs = {'aria-controls': id, 'aria-expanded': 'false'};
  const button = {getAttribute: k => attrs[k], setAttribute: (k,v) => attrs[k]=v,
                  querySelector: () => ({textContent: ''})};
  return {querySelector: () => button};
}
let rows = [makeRow('first'), makeRow('second')];
global.document = {addEventListener: (name, fn) => {assert.equal(name, 'click'); click=fn;},
  querySelectorAll: () => rows, getElementById: id => details[id]};
__SCRIPT__
function press(row, reference=false) {
  click({target: {closest: selector => selector === 'tr[data-register-row]' ? row : reference}});
}
press(rows[0]); assert.equal(details.first.hidden, false);
press(rows[0]); assert.equal(details.first.hidden, true);
press(rows[0]); press(rows[1]);
assert.equal(details.first.hidden, true); assert.equal(details.second.hidden, false);
press(rows[1], true); assert.equal(details.second.hidden, false);
// Newly rendered main content uses the same delegated listener.
rows = [makeRow('replacement')]; press(rows[0]); assert.equal(details.replacement.hidden, false);
'''
    subprocess.run([node, '-e', harness.replace('__SCRIPT__', _REGISTER_SCRIPT)], check=True, capture_output=True)


def test_navigation_legend_and_section_anchors():
    report = render_html("# Plan\n\n## 1. Overview\n\ntext\n\n## 2. Checks\n\ntext\n")
    assert '<nav class="toc"' in report and 'class="legend"' in report
    assert 'href="#sec-1-overview"' in report and 'id="sec-2-checks"' in report
    assert "<h2>1. Overview</h2>" in report


def test_table_cells_get_status_pills_muted_empties_and_labelled_details():
    md = ("| Item | Details | Value | Status |\n| --- | --- | --- | --- |\n"
          "| a | Where: monitor<br>Why: spec<br>Note: x<br>Extra: y<br>More: z | unknown | NOT_RUN |\n"
          "| b | - | not stated | PASS |\n")
    report = render_html(md)
    assert '<span class="k">Where:</span>' in report and '<details class="more"><summary>2 more</summary>' in report
    assert report.count('class="empty"') == 3 and 'class="status status-not_run"' in report
    assert "unknown" not in report.split("<main>")[1]


def test_reference_excerpts_keep_line_breaks_and_link_chunk_ids_back():
    badge_md = badge("DOCUMENTED", ["CH-aaaaaaaaaa"], "")
    md = (f"## Section\n\nClaim {badge_md}. Also see CH-aaaaaaaaaa and CH-bbbbbbbbbb.\n\n"
          "## Reference evidence\n\n### Reference CH-aaaaaaaaaa\n\nSource: doc.pdf, p.1\n\n> Bit # Access\n> 0 R Delta\n")
    report = render_html(md)
    assert '<pre class="excerpt">Bit # Access\n0 R Delta</pre>' in report
    assert 'class="backref" href="#cite-1"' in report and 'id="cite-1"' in report
    assert 'class="cref" href="#reference-CH-aaaaaaaaaa"' in report
    assert 'href="#reference-CH-bbbbbbbbbb"' not in report  # no excerpt for it: plain text


def test_long_rtl_source_lists_are_collapsed():
    md = ("### OBS-1\n\n- **RTL sources:** rtl/uart.v (5 excerpts)\n" + "".join(f"  - lines {n} (SRC:{n})\n" for n in range(5)))
    assert '<details class="src-list"><summary>' in render_html(md)


def test_tooltips_use_a_viewport_popup_script():
    report = render_html("text")
    assert 'id="testplan-tooltips"' in report and "evidence-popup" in report and "beforeprint" in report


def test_inference_notes_are_collapsible_in_bullets_and_cells():
    md = ("- Claim ⚠️\n  - Inference: derived from the cited register list.\n\n"
          "| # | Description | Details |\n| --- | --- | --- |\n"
          "| 1 | Check x<br/>Where: monitor<br/>Inference: reason here | Sampling: CLK<br/>Inference: other |\n")
    report = render_html(md)
    assert report.count('<details class="inference">') == 3
    assert "<summary><span aria-hidden=\"true\">⚠️</span> Inference</summary>" in report
    assert report.index("Where:") < report.index("reason here")  # folded notes follow the visible ones


def test_review_and_rtl_approval_terms_are_highlighted():
    md = ("- NEEDS_REVIEW: RTL design engineer approval required.\n- Pending RTL designer review of the pulse.\n"
          "- Owner RTL_DESIGN_ENGINEER decides.\n")
    report = render_html(md)
    assert report.count('<mark class="review">') == 4
    assert '<mark class="review">NEEDS_REVIEW</mark>' in report
    assert '<mark class="review">RTL design engineer approval required</mark>' in report


def test_description_cell_leads_with_statement_and_coverage_status_is_a_pill():
    md = ("| # | Description | Covergroup | Covered |\n| --- | --- | --- | --- |\n"
          "| 1 | Cover x: y is covered.<br/>Sampled on ACK | cg_x | NOT_COVERED |\n")
    report = render_html(md)
    assert '<div class="desc">Cover x: y is covered.</div>' in report
    assert 'status-not_covered' in report and "Not covered" in report
    assert '<span class="k">Cover x:' not in report


def test_indicator_tooltip_names_its_sources():
    from dv_agent.report.provenance_badge import source_summaries
    marked = source_summaries(badge("DOCUMENTED", ["CH-1"]) + " x", {"CH-1": {"path": "spec.pdf", "page": 6, "excerpt": "WB_CYC_I bus cycle"}})
    report = render_html("- text " + marked + "\n")
    assert "Sources: spec.pdf, p.6" in report and "Source excerpt: WB_CYC_I bus cycle" in report


def test_citation_anchor_keeps_attributes_separated():
    report = render_html("- x " + badge("DOCUMENTED", ["CH-1"]) + "\n\n## Reference evidence\n\n### Reference CH-1\n\nSource: s\n")
    assert 'id="cite-1" tabindex="0"' in report


def test_sources_tip_renders_excerpt_tooltip():
    from dv_agent.report.provenance_badge import cite_marker, source_tip_summaries
    md = "- entry text" + cite_marker(["CH-1", "REQ-9"]) + "\n"
    assert "— sources:" not in md
    enriched = source_tip_summaries(md, {"CH-1": {"path": "spec.pdf", "page": 6,
                                                 "summary": "WB_CYC_I bus cycle"}})
    assert enriched != md  # excerpts embedded
    assert source_tip_summaries(enriched, {}) == enriched  # idempotent
    report = render_html(enriched)
    assert 'aria-label="Sources: CH-1, REQ-9"' in report
    assert "WB_CYC_I bus cycle" in report
    assert 'href="#reference-CH-1"' in report and 'href="#reference-REQ-9"' in report


def test_sources_tip_without_index_links_ids_only():
    from dv_agent.report.provenance_badge import cite_marker
    report = render_html("- entry text" + cite_marker(["CH-2"]) + "\n")
    assert 'aria-label="Sources: CH-2"' in report
    assert 'href="#reference-CH-2"' in report


def test_sources_tip_garbage_degrades_to_icon():
    report = render_html("- entry text 📄<!--dv-sources:!!!not-valid!!! -->\n")
    assert "📄" in report and '<span class="evidence-tooltip"' not in report


def test_cite_marker_rejects_empty_and_bad_ids():
    from dv_agent.report.provenance_badge import cite_marker, decode_sources
    assert cite_marker([]) == ""
    assert cite_marker(["CH-1", "bogus id!", "CH-1"]) == " 📄<!--dv-sources:CH-1-->"
    with pytest.raises(ValueError):
        decode_sources("bogus id!")
