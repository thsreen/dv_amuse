"""Offline HTML view of the Markdown emitted by our report renderers.

Markdown is the single presentation source. This intentionally handles the
report's headings, lists, tables, quotes, fences and inline formatting rather
than accepting arbitrary HTML from model-generated text.
"""
import html
import re
from urllib.parse import urlsplit

from .provenance_badge import decode


_INLINE = re.compile(r"(✅|⚠️|🛑)<!--dv-evidence:([A-Za-z0-9_-]+)-->|(`+)(.+?)\3|\*\*(.+?)\*\*|(?<!\w)_(.+?)_(?!\w)|"
                     r"\[([^\]]+)\]\(([^\s)]+)\)|<br\s*/?>|\\([|*_`])", re.I)


def _inline(text: str) -> str:
    parts, start = [], 0
    for m in _INLINE.finditer(text):
        parts.append(html.escape(text[start:m.start()]))
        if m[1] is not None:
            try:
                info = decode(m[2])
                refs = "".join(f'<a href="#reference-{html.escape(str(cid), quote=True)}">{html.escape(str(cid))}</a>'
                               for cid in info["citations"] if re.fullmatch(r"[A-Za-z0-9_-]+", str(cid)))
                reason = f'<span>Reason: {html.escape(info["reason"])}</span>' if info["reason"] else ""
                label = {"DOCUMENTED": "Documented", "INFERRED": "Inferred", "NO_REFERENCE": "No verified reference"}[info["state"]]
                parts.append(f'<span class="evidence-badge" tabindex="0" aria-label="{label}">{m[1]}'
                             f'<span class="evidence-tooltip" role="tooltip"><strong>{label}</strong>{reason}{refs}</span></span>')
            except (ValueError, KeyError, TypeError):
                parts.append(html.escape(m[1]))
        elif m[4] is not None:
            parts.append(f"<code>{html.escape(m[4])}</code>")
        elif m[5] is not None:
            parts.append(f"<strong>{_inline(m[5])}</strong>")
        elif m[6] is not None:
            parts.append(f"<em>{_inline(m[6])}</em>")
        elif m[7] is not None:
            label, target = m[7], m[8]
            # Local links and http(s) only. Preserve unsafe targets as visible text.
            if urlsplit(target).scheme.lower() in ("", "http", "https", "mailto"):
                parts.append(f'<a href="{html.escape(target, quote=True)}">{_inline(label)}</a>')
            else:
                parts.append(html.escape(m[0]))
        elif m[9] is not None:
            parts.append(html.escape(m[9]))
        else:
            parts.append("<br>")
        start = m.end()
    parts.append(html.escape(text[start:]))
    return "".join(parts)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def _separator(line: str) -> bool:
    return bool(line.strip().startswith("|")) and all(re.fullmatch(r":?-{3,}:?", c) for c in _cells(line))


def _blocks(lines: list[str]) -> str:
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level = len(heading[1])
            reference = re.fullmatch(r"Reference ([A-Za-z0-9_-]+)", heading[2])
            anchor = f' id="reference-{reference[1]}"' if reference else ""
            out.append(f"<h{level}{anchor}>{_inline(heading[2])}</h{level}>")
            i += 1
        elif line.startswith("```"):
            body = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            out.append("<pre><code>" + html.escape("\n".join(body)) + "</code></pre>")
            i += 1
        elif i + 1 < len(lines) and line.lstrip().startswith("|") and _separator(lines[i + 1]):
            head = "".join(f"<th scope=\"col\">{_inline(c)}</th>" for c in _cells(line))
            rows = []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _cells(lines[i])) + "</tr>")
                i += 1
            out.append(f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")
        elif line.startswith(">"):
            body = []
            while i < len(lines) and lines[i].startswith(">"):
                body.append(lines[i][1:].lstrip())
                i += 1
            out.append("<blockquote>" + _blocks(body) + "</blockquote>")
        elif re.match(r"^\s*[-*]\s+", line):
            base = len(line) - len(line.lstrip())
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                indent = len(lines[i]) - len(lines[i].lstrip())
                if indent < base:
                    break
                text = re.sub(r"^\s*[-*]\s+", "", lines[i])
                i += 1
                children = []
                while i < len(lines) and lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) > base:
                    children.append(lines[i])
                    i += 1
                items.append("<li>" + _inline(text) + (_blocks(children) if children else "") + "</li>")
            out.append("<ul>" + "".join(items) + "</ul>")
        else:
            # A line break is sufficient for generated prose; no content rewrite.
            out.append("<p>" + _inline(line) + "</p>")
            i += 1
    return "\n".join(out)


_STYLE = """
:root { color-scheme: light; font-family: system-ui, sans-serif; color: #203047; background: #eef2f6; }
body { margin: 0; padding: 2rem 1rem; line-height: 1.6; }
main { max-width: 1240px; margin: auto; padding: 2.5rem; background: white; border-radius: 12px; }
h1, h2, h3 { line-height: 1.3; color: #153451; overflow-wrap: anywhere; }
h1 { font-size: 2rem; } h2 { margin-top: 2.5rem; padding-bottom: .5rem; border-bottom: 2px solid #dce5ef; }
h3 { margin-top: 1.8rem; } p, li, td { overflow-wrap: anywhere; }
a { color: #165bbb; } li { margin: .35rem 0; }
code { background: #eef2f6; padding: .1rem .3rem; border-radius: 3px; }
pre { overflow-x: auto; background: #eef2f6; padding: 1rem; } pre code { padding: 0; }
blockquote { margin: 1rem 0; padding: .5rem 1rem; background: #fff8e8; border-left: 4px solid #d99d30; }
blockquote p { margin: .25rem 0; }
.table-wrap { overflow-x: auto; margin: 1rem 0; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th { background: #e9eff6; text-align: left; } th, td { border: 1px solid #d7e0eb; padding: .6rem .75rem; vertical-align: top; min-width: 5rem; }
tbody tr:nth-child(even) { background: #f7f9fc; }
.evidence-badge { display: inline-block; position: relative; cursor: help; margin-right: .2rem; }
.evidence-tooltip { display: none; position: absolute; z-index: 5; top: 1.5rem; left: 0; width: min(27rem, 85vw); padding: .65rem; color: #203047; background: #fff; border: 1px solid #9bafc5; border-radius: 6px; box-shadow: 0 4px 16px #20304733; text-align: left; font-size: .86rem; white-space: normal; }
.evidence-tooltip span, .evidence-tooltip a { display: block; margin-top: .35rem; overflow-wrap: anywhere; }
.evidence-badge:hover .evidence-tooltip, .evidence-badge:focus-within .evidence-tooltip { display: block; }
.report-tools { max-width: 1240px; margin: 0 auto 1rem; display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
.report-tools button { font: inherit; font-weight: 600; color: white; background: #165bbb; border: 0; border-radius: 6px; padding: .65rem 1rem; cursor: pointer; }
.report-tools button:disabled { opacity: .65; cursor: wait; }
.report-tools button:focus-visible { outline: 3px solid #82aff3; outline-offset: 3px; }
.report-tools label { font-weight: 600; }
.report-tools select { font: inherit; max-width: min(24rem, 90vw); padding: .55rem; border: 1px solid #9bafc5; border-radius: 6px; background: white; }
.report-tools p { margin: 0; font-size: .9rem; flex: 1; min-width: 200px; }
@media (max-width: 700px) { body { padding: 0; } main { padding: 1rem; border-radius: 0; } }
@media print { .report-tools { display: none; } body, main { background: white; padding: 0; } .table-wrap { overflow: visible; } table { font-size: 8pt; } h2, h3 { break-after: avoid; } tr { break-inside: avoid; } }
"""


_CONTROLS_SCRIPT = """
(() => {
  const button = document.getElementById('render-testplan');
  const status = document.getElementById('render-status');
  const selector = document.getElementById('testplan-select');
  button.disabled = window.location.protocol !== 'file:';
  if (window.location.protocol === 'file:') {
    selector.replaceChildren();
    const option = document.createElement('option');
    option.textContent = 'Open the local viewer to choose a testplan';
    selector.appendChild(option);
    selector.disabled = true;
  }
  if (['http:', 'https:'].includes(window.location.protocol)) {
    fetch('/plans', {cache: 'no-store'}).then(async response => {
      if (!response.ok) throw new Error('Could not load testplans.');
      const catalog = await response.json();
      selector.replaceChildren();
      for (const plan of catalog.plans) {
        const option = document.createElement('option');
        option.value = plan.id;
        option.textContent = plan.label;
        selector.appendChild(option);
      }
      selector.value = new URLSearchParams(window.location.search).get('plan') || catalog.selected || '';
      selector.disabled = catalog.plans.length === 0;
      button.disabled = catalog.plans.length === 0;
    }).catch(error => { status.textContent = 'Testplan list unavailable: ' + error.message; });
  }
  selector.addEventListener('change', () => {
    window.location.assign('/?plan=' + encodeURIComponent(selector.value));
  });
  button.addEventListener('click', async () => {
    if (!['http:', 'https:'].includes(window.location.protocol)) {
      status.textContent = 'Open this report in the local viewer: dv-agent render-testplan --out <run-directory> --serve. Then click Render testplan at the printed URL.';
      return;
    }
    button.disabled = true;
    status.textContent = 'Rendering the latest Markdown…';
    try {
      const plan = selector.value;
      const response = await fetch('/render' + (plan ? '?plan=' + encodeURIComponent(plan) : ''), {
        method: 'POST', headers: {'X-Testplan-Render': '1'}, cache: 'no-store'
      });
      if (!response.ok) {
        const problem = await response.json();
        throw new Error(problem.error || 'Could not render the testplan.');
      }
      const updated = new DOMParser().parseFromString(await response.text(), 'text/html');
      const report = updated.querySelector('main');
      if (!report) throw new Error('The viewer returned an invalid report.');
      document.querySelector('main').replaceWith(document.importNode(report, true));
      status.textContent = 'Rendered the latest Markdown and saved testplan_doc.html.';
    } catch (error) {
      status.textContent = 'Render failed: ' + error.message;
    } finally {
      button.disabled = false;
    }
  });
})();
"""


def render_html(markdown: str, title: str = "Verification test plan") -> str:
    """Render exactly this Markdown report, with no LLM call or external assets."""
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>\n"
            '<body><div class="report-tools" role="region" aria-label="Testplan controls">'
            '<label for="testplan-select">Testplan</label><select id="testplan-select" aria-label="Select testplan">'
            '<option value="">Loading testplans…</option></select>'
            '<button type="button" id="render-testplan" aria-describedby="render-status">Render testplan</button>'
            '<p id="render-status" role="status" aria-live="polite">Refresh this report from the latest saved Markdown.</p>'
            '</div><main>\n' + _blocks(markdown.splitlines()) + '\n</main>'
            f'<script id="testplan-controls">{_CONTROLS_SCRIPT}</script></body></html>\n')
