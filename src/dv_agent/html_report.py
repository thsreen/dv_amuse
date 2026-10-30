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


_CHUNK_REF = re.compile(r"\bCH-[0-9a-f]{10}\b")


def _plain(text: str) -> str:
    """Escape text and link bare chunk IDs to their reference excerpt (unresolved links are removed later)."""
    out, start = [], 0
    for m in _CHUNK_REF.finditer(text):
        out.append(html.escape(text[start:m.start()]))
        out.append(f'<a class="cref" href="#reference-{m[0]}">{m[0]}</a>')
        start = m.end()
    out.append(html.escape(text[start:]))
    return "".join(out)


def _inline(text: str) -> str:
    parts, start = [], 0
    for m in _INLINE.finditer(text):
        parts.append(_plain(text[start:m.start()]))
        if m[1] is not None:
            try:
                info = decode(m[2])
                refs = "".join(f'<a href="#reference-{html.escape(str(cid), quote=True)}">{html.escape(str(cid))}</a>'
                               for cid in info["citations"] if re.fullmatch(r"[A-Za-z0-9_-]+", str(cid)))
                reason = f'<span>Reason: {html.escape(info["reason"])}</span>' if info["reason"] else ""
                summary = (f'<span>Source excerpt: {html.escape(str(info["summary"]))}</span>'
                           if info.get("summary") else "")
                label = {"DOCUMENTED": "Documented", "INFERRED": "Inferred", "NO_REFERENCE": "No verified reference"}[info["state"]]
                parts.append(f'<span class="evidence-badge" tabindex="0" aria-label="{label}">{m[1]}'
                             f'<span class="evidence-tooltip" role="tooltip"><strong>{label}</strong>{summary}{reason}{refs}</span></span>')
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
    parts.append(_plain(text[start:]))
    return "".join(parts)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def _separator(line: str) -> bool:
    return bool(line.strip().startswith("|")) and all(re.fullmatch(r":?-{3,}:?", c) for c in _cells(line))


_EMPTY = {"-": "—", "–": "—", "—": "—", "unknown": "not stated", "not stated": "not stated",
          "not applicable": "not applicable"}
_STATUS = re.compile(r"PASS|FAIL|NOT_RUN|BLOCKED|NEEDS_REVIEW")
_STATUS_MARK = {"PASS": "✓", "FAIL": "✗", "NOT_RUN": "○", "BLOCKED": "■", "NEEDS_REVIEW": "◔"}
_KV = re.compile(r"^(\*{0,2}[A-Za-z][^:*]{0,40}?:\*{0,2})\s+(.+)$")
_BR = re.compile(r"<br\s*/?>", re.I)
LONG_CELL = 160
TALL_ROWS = 12


def _kv(segment: str) -> str:
    m = _KV.match(segment)
    if m:
        return f'<div class="kv"><span class="k">{_inline(m[1])}</span> {_inline(m[2])}</div>'
    return f'<div class="kv">{_inline(segment)}</div>'


def _cell(raw: str) -> str:
    """One table cell: muted empty values, status pills, labelled detail lists, readable long text."""
    text = raw.strip()
    if text.lower() in _EMPTY:
        return f'<td><span class="empty">{_EMPTY[text.lower()]}</span></td>'
    if _STATUS.fullmatch(text):
        return (f'<td><span class="status status-{text.lower()}"><span aria-hidden="true">{_STATUS_MARK[text]}</span> '
                f'{text}</span></td>')
    segments = [x.strip() for x in _BR.split(text) if x.strip()]
    if len(segments) >= 2:
        keep = 3 if len(segments) > 4 else len(segments)
        shown = "".join(_kv(x) for x in segments[:keep])
        rest = segments[keep:]
        if rest:
            shown += (f'<details class="more"><summary>{len(rest)} more</summary>'
                      + "".join(_kv(x) for x in rest) + '</details>')
        return f'<td class="detail">{shown}</td>'
    if len(re.sub(r"<!--.*?-->", "", text)) > LONG_CELL:
        return f'<td class="long">{_inline(text)}</td>'
    return f"<td>{_inline(text)}</td>"


def _blocks(lines: list[str], excerpt: bool = False) -> str:
    out, i = [], 0
    reference_mode = excerpt
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        register = re.fullmatch(r"<!--dv-register-detail:([a-f0-9]{16})-->", line)
        if (line == "<!--dv-rtl-observations-->" and i + 1 < len(lines)
                and lines[i + 1].startswith("## ") and "<!--dv-rtl-observations-end-->" in lines[i + 2:]):
            end = lines.index("<!--dv-rtl-observations-end-->", i + 2)
            out.append('<details class="rtl-observations"><summary><h2>' + _inline(lines[i + 1][3:])
                       + '</h2></summary>' + _blocks(lines[i + 2:end]) + '</details>')
            i = end + 1
        elif register and "<!--dv-register-detail-end-->" in lines[i + 1:]:
            end = lines.index("<!--dv-register-detail-end-->", i + 1)
            out.append(f'<section data-register-detail="{register[1]}">'
                       + _blocks(lines[i + 1:end]) + '</section>')
            i = end + 1
        elif (line == "<details>" and i + 1 < len(lines)
                and lines[i + 1] in ("<summary>Specification evidence</summary>",
                                     "<summary>ⓘ Interface info</summary>")
                and "</details>" in lines[i + 2:]):
            end = lines.index("</details>", i + 2)
            if lines[i + 1] == "<summary>ⓘ Interface info</summary>":
                out.append('<details class="interface-info"><summary>ⓘ Interface info</summary>'
                           + _blocks(lines[i + 2:end]) + '</details>')
            else:
                out.append('<details class="source-quotes"><summary>Specification evidence</summary>'
                           + _blocks(lines[i + 2:end], excerpt=True) + '</details>')
            i = end + 1
        elif heading:
            level = len(heading[1])
            reference = re.fullmatch(r"Reference ([A-Za-z0-9_-]+)", heading[2])
            anchor = f' id="reference-{reference[1]}"' if reference else ""
            if reference:
                reference_mode = True
            elif level <= 2:
                reference_mode = excerpt
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
                cells = _cells(lines[i])
                marker = re.search(r"<!--dv-register:([a-f0-9]{16})-->", cells[0])
                if marker:
                    key = marker[1]
                    cells[0] = cells[0].replace(marker[0], "")
                    button = (f'<button type="button" class="register-toggle" aria-expanded="false" '
                              f'aria-controls="register-detail-{key}"><span aria-hidden="true">▸</span> '
                              + _inline(cells[0]) + '</button>')
                    rows.append(f'<tr data-register-row="{key}"><td>{button}</td>'
                                + ''.join(_cell(c) for c in cells[1:]) + '</tr>')
                else:
                    rows.append("<tr>" + "".join(_cell(c) for c in cells) + "</tr>")
                i += 1
            wrap = "table-wrap tall" if len(rows) > TALL_ROWS else "table-wrap"
            out.append(f'<div class="{wrap}" tabindex="0"><table><thead><tr>{head}</tr></thead><tbody>'
                       + "".join(rows) + "</tbody></table></div>")
        elif line.startswith(">"):
            body = []
            while i < len(lines) and lines[i].startswith(">"):
                body.append(lines[i][1:].lstrip())
                i += 1
            if reference_mode:
                out.append('<blockquote><pre class="excerpt">' + html.escape("\n".join(body).strip("\n")) + "</pre></blockquote>")
            else:
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
                if text.startswith("**RTL source") and sum(1 for c in children if re.match(r"\s*[-*]\s", c)) >= 4:
                    items.append('<li><details class="src-list"><summary>' + _inline(text) + "</summary>"
                                 + _blocks(children) + "</details></li>")
                else:
                    items.append("<li>" + _inline(text) + (_blocks(children) if children else "") + "</li>")
            out.append("<ul>" + "".join(items) + "</ul>")
        else:
            # A line break is sufficient for generated prose; no content rewrite.
            css = ' class="provenance-note"' if line.startswith("_Provenance:") else ""
            out.append("<p" + css + ">" + _inline(line) + "</p>")
            i += 1
    return "\n".join(out)


_STYLE = """
:root { color-scheme: light; font-family: system-ui, sans-serif; color: #203047; background: #eef2f6; }
body { margin: 0; padding: 2rem 1rem; line-height: 1.6; }
main { max-width: 1240px; margin: auto; padding: 2.5rem; background: white; border-radius: 12px; }
h1, h2, h3 { line-height: 1.3; color: #153451; overflow-wrap: anywhere; }
h1 { font-size: 2rem; } h2 { margin-top: 2.5rem; padding-bottom: .5rem; border-bottom: 2px solid #dce5ef; }
h3 { margin-top: 1.8rem; } p, li, td { overflow-wrap: anywhere; }
h3, h4 { font-weight: 700; }
h3 { padding-left: .65rem; border-left: 3px solid #9bafc5; }
.provenance-note { font-size: .82rem; color: #64748b; margin-top: -.4rem; }
a { color: #165bbb; } li { margin: .35rem 0; }
code { background: #eef2f6; padding: .1rem .3rem; border-radius: 3px; }
pre { overflow-x: auto; background: #eef2f6; padding: 1rem; } pre code { padding: 0; }
blockquote { margin: 1rem 0; padding: .5rem 1rem; background: #fff8e8; border-left: 4px solid #d99d30; }
blockquote p { margin: .25rem 0; }
details.source-quotes { margin: 1rem 0; padding: .5rem 1rem; border: 1px solid #dce5ef; border-radius: 6px; }
details.source-quotes summary { cursor: pointer; font-weight: 600; }
details.interface-info { margin: .4rem 0 1rem; padding: .35rem .9rem; border: 1px solid #cfe0f3; border-left: 4px solid #165bbb; border-radius: 6px; background: #f4f8fd; font-size: .92rem; }
details.interface-info summary { cursor: pointer; color: #165bbb; font-weight: 600; }
details.interface-info ul { margin: .4rem 0; padding-left: 1.2rem; }
.rtl-observations { margin: 2rem 0; border-bottom: 1px solid #dce5ef; }
.rtl-observations > summary { cursor: pointer; font-weight: 700; color: #153451; }
.rtl-observations > summary > h2 { display: inline; margin: 0; border: 0; font-weight: 700; }
.rtl-observations[open] > summary { margin-bottom: 1rem; }
.table-wrap { overflow-x: auto; margin: 1rem 0; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th { background: #e9eff6; text-align: left; } th, td { border: 1px solid #d7e0eb; padding: .6rem .75rem; vertical-align: top; min-width: 5rem; }
tbody tr:nth-child(even) { background: #f7f9fc; }
tr[data-register-row] { cursor: pointer; }
tr[data-register-row]:hover { background: #e9eff6; }
.register-toggle { background: none; border: 0; color: #165bbb; padding: 0; font: inherit; font-weight: 600; text-align: left; cursor: pointer; }
.register-toggle:focus-visible { outline: 2px solid #165bbb; outline-offset: 4px; }
.register-detail-row > td { padding: 1rem 1.5rem; background: #f7f9fc; }
@media print { .register-detail-row[hidden] { display: table-row; } }
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
.anchor { display: block; position: relative; top: -4rem; height: 0; }
.toc { position: sticky; top: 0; z-index: 20; margin: -2.5rem -2.5rem 1.5rem; padding: .55rem 2.5rem; background: #fffffff2; border-bottom: 1px solid #dce5ef; display: flex; gap: .5rem; align-items: center; overflow-x: auto; white-space: nowrap; }
.toc > span { font-size: .8rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: .04em; }
.toc a { font-size: .85rem; padding: .2rem .6rem; border: 1px solid #c9d6e4; border-radius: 999px; text-decoration: none; color: #153451; background: #f3f6fa; }
.toc a:hover, .toc a:focus-visible { background: #dce9fb; border-color: #165bbb; }
.legend { margin: 1rem 0; padding: .6rem .9rem; font-size: .88rem; border: 1px solid #dce5ef; border-radius: 6px; background: #f7f9fc; }
.legend b { font-weight: 700; } .legend .item { display: inline-block; margin-right: 1.2rem; }
blockquote:has(> pre.excerpt) { background: #f7f9fc; border-left-color: #9bafc5; }
pre.excerpt { margin: 0; padding: 0; background: none; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; font-size: .88rem; color: #33475f; }
.backref { margin-left: .6rem; font-size: .8rem; font-weight: 400; }
.empty { color: #7b8aa0; font-style: italic; }
.status { display: inline-block; padding: .05rem .5rem; border-radius: 999px; font-size: .8rem; font-weight: 700; white-space: nowrap; border: 1px solid #b6c4d6; background: #eef2f6; color: #33475f; }
.status-pass { background: #e3f5ea; border-color: #7bc596; color: #17603a; } .status-fail { background: #fde8e8; border-color: #e08a8a; color: #8c1d1d; }
.status-blocked { background: #fdecd8; border-color: #e0a45f; color: #7a4510; } .status-needs_review { background: #fff4cf; border-color: #d9b84a; color: #6b5200; }
td.long { min-width: 16rem; max-width: 34rem; } td.detail { min-width: 16rem; max-width: 36rem; }
.kv { margin: .15rem 0; } .kv .k { font-weight: 600; color: #3b4f68; }
details.more, details.src-list { margin-top: .3rem; } details.more > summary, details.src-list > summary { cursor: pointer; color: #165bbb; }
.table-wrap:focus-visible { outline: 2px solid #165bbb; outline-offset: 2px; }
.table-wrap.tall { max-height: 75vh; overflow: auto; }
.table-wrap.tall th { position: sticky; top: 0; z-index: 2; }
html.js-tips .evidence-tooltip { display: none !important; }
#evidence-popup { position: fixed; z-index: 50; width: min(27rem, calc(100vw - 16px)); padding: .65rem; color: #203047; background: #fff; border: 1px solid #9bafc5; border-radius: 6px; box-shadow: 0 4px 16px #20304733; font-size: .86rem; line-height: 1.45; }
#evidence-popup[hidden] { display: none; }
#evidence-popup span, #evidence-popup a { display: block; margin-top: .35rem; overflow-wrap: anywhere; }
@media (max-width: 700px) { .toc { margin: -1rem -1rem 1rem; padding: .5rem 1rem; } body { padding: 0; } main { padding: 1rem; border-radius: 0; } }
@media print { .report-tools, .toc, #evidence-popup { display: none; } .evidence-badge::after { content: " [" attr(aria-label) "]"; font-size: .7em; } .table-wrap.tall { max-height: none; overflow: visible; } body, main { background: white; padding: 0; } .table-wrap { overflow: visible; } table { font-size: 8pt; } h2, h3 { break-after: avoid; } tr { break-inside: avoid; } }
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


_LEGEND = ('<aside class="legend" aria-label="How to read this report"><span class="item"><b>✅ Documented</b>: stated in the cited '
           'source</span><span class="item"><b>⚠️ Inferred</b>: reasoning shown on hover, focus or tap; needs review</span>'
           '<span class="item"><b>🛑 No verified reference</b>: no checked citation</span>'
           '<span class="item"><b>NOT_RUN / NEEDS_REVIEW</b>: execution and review state, not a verdict</span></aside>')


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", html.unescape(text)).lower()).strip("-")[:48] or "section"


def _decorate(body: str) -> str:
    """Section anchors, a contents bar, the legend, citation back-links and resolved chunk links."""
    chips, used = [], set()

    def heading(m):
        title = re.sub(r"<[^>]+>", "", html.unescape(m[3]))
        ident = base = "sec-" + _slug(title)
        n = 2
        while ident in used:
            ident, n = f"{base}-{n}", n + 1
        used.add(ident)
        chips.append((ident, title))
        return f'<span class="anchor" id="{ident}"></span>{m[1] or ""}<h2{m[2] or ""}>{m[3]}</h2>'

    body = re.sub(r'(<details class="rtl-observations"><summary>)?<h2( id="[^"]*")?>(.*?)</h2>', heading, body)
    # Citation back-links: first badge that cites each reference.
    first, n = {}, 0

    def badge(m):
        nonlocal n
        n += 1
        for ref in re.findall(r'href="#reference-([A-Za-z0-9_-]+)"', m[2]):
            first.setdefault(ref, f"cite-{n}")
        return f'{m[1]} id="cite-{n}"{m[2]}'

    body = re.sub(r'(<span class="evidence-badge") (tabindex="0".*?</span></span>)', badge, body, flags=re.S)
    known = set(re.findall(r'<h3 id="reference-([A-Za-z0-9_-]+)"', body))
    body = re.sub(r'<h3 id="reference-([A-Za-z0-9_-]+)">(.*?)</h3>',
                  lambda m: (f'<h3 id="reference-{m[1]}">{m[2]}'
                             + (f'<a class="backref" href="#{first[m[1]]}">↩ first cited</a>' if m[1] in first else "")
                             + "</h3>"), body)
    body = re.sub(r'<a class="cref" href="#reference-([A-Za-z0-9_-]+)">([^<]*)</a>',
                  lambda m: m[0] if m[1] in known else m[2], body)
    if chips:
        nav = ('<nav class="toc" aria-label="Contents"><span>Contents</span>'
               + "".join(f'<a href="#{i}" title="{html.escape(t, quote=True)}">{html.escape(t if len(t) <= 34 else t[:33] + "…")}</a>'
                         for i, t in chips) + "</nav>")
        body = nav + "\n" + body
    return re.sub(r"(</h1>)", r"\1\n" + _LEGEND.replace("\\", "\\\\"), body, count=1) if "</h1>" in body else body


def render_html(markdown: str, title: str = "Verification test plan") -> str:
    """Render exactly this Markdown report, with no LLM call or external assets."""
    body = _decorate(_blocks(markdown.splitlines()))
    details = dict(re.findall(r'<section data-register-detail="([a-f0-9]{16})">(.*?)</section>', body, re.S))
    for key, content in details.items():
        row = re.search(rf'<tr data-register-row="{key}">(.*?)</tr>', body, re.S)
        if row:
            columns = row[1].count('<td>')
            body = body.replace(row[0], row[0] + f'<tr id="register-detail-{key}" class="register-detail-row" hidden>'
                                + f'<td colspan="{columns}">{content}</td></tr>', 1)
            body = body.replace(f'<section data-register-detail="{key}">{content}</section>', '', 1)
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>\n"
            '<body><div class="report-tools" role="region" aria-label="Testplan controls">'
            '<label for="testplan-select">Testplan</label><select id="testplan-select" aria-label="Select testplan">'
            '<option value="">Local viewer needed to switch testplans</option></select>'
            '<button type="button" id="render-testplan" aria-describedby="render-status">Render testplan</button>'
            '<p id="render-status" role="status" aria-live="polite">Refresh this report from the latest saved Markdown.</p>'
            '</div><noscript><style>.register-detail-row[hidden]{display:table-row;}</style></noscript><main>\n' + body + '\n</main>'
            f'<script id="testplan-registers">{_REGISTER_SCRIPT}</script>'
            f'<script id="testplan-tooltips">{_TOOLTIP_SCRIPT}</script>'
            f'<script id="testplan-controls">{_CONTROLS_SCRIPT}</script></body></html>\n')


_TOOLTIP_SCRIPT = """
(() => {
  if (window.__evidencePopup) return;
  window.__evidencePopup = true;
  document.documentElement.classList.add('js-tips');
  const pop = document.createElement('div');
  pop.id = 'evidence-popup'; pop.setAttribute('role', 'tooltip'); pop.hidden = true;
  document.body.appendChild(pop);
  let pinned = null, timer = null;
  function hide() { pop.hidden = true; pinned = null; }
  function show(badge) {
    const tip = badge.querySelector('.evidence-tooltip');
    if (!tip) return;
    clearTimeout(timer);
    pop.replaceChildren(...Array.from(tip.childNodes).map(n => n.cloneNode(true)));
    pop.hidden = false;
    const r = badge.getBoundingClientRect();
    const left = Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8));
    let top = r.bottom + 6;
    if (top + pop.offsetHeight > window.innerHeight - 8) top = Math.max(8, r.top - pop.offsetHeight - 6);
    pop.style.left = left + 'px'; pop.style.top = top + 'px';
  }
  const badgeOf = e => e.target.closest && e.target.closest('.evidence-badge');
  document.addEventListener('mouseover', e => { const b = badgeOf(e); if (b && !pinned) show(b); });
  document.addEventListener('mouseout', e => { if (badgeOf(e) && !pinned) timer = setTimeout(hide, 180); });
  pop.addEventListener('mouseenter', () => clearTimeout(timer));
  pop.addEventListener('mouseleave', () => { if (!pinned) hide(); });
  document.addEventListener('focusin', e => { const b = badgeOf(e); if (b) show(b); });
  document.addEventListener('focusout', e => { if (badgeOf(e) && !pinned) timer = setTimeout(hide, 180); });
  document.addEventListener('click', e => {
    const b = badgeOf(e);
    if (b) { if (pinned === b) hide(); else { show(b); pinned = b; } return; }
    if (!pop.contains(e.target)) hide();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') hide(); });
  window.addEventListener('scroll', () => { if (!pinned) hide(); }, true);
  let reopened = [];
  window.addEventListener('beforeprint', () => {
    reopened = Array.from(document.querySelectorAll('details:not([open])'));
    reopened.forEach(d => d.setAttribute('open', ''));
  });
  window.addEventListener('afterprint', () => reopened.forEach(d => d.removeAttribute('open')));
})();
"""


_REGISTER_SCRIPT = """
(() => {
  function setOpen(row, open) {
    const button = row.querySelector('.register-toggle');
    const detail = document.getElementById(button.getAttribute('aria-controls'));
    if (!detail) return;
    detail.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    button.querySelector('span').textContent = open ? '▾' : '▸';
  }
  document.addEventListener('click', event => {
    const row = event.target.closest('tr[data-register-row]');
    if (!row) return;
    if (event.target.closest('a, .evidence-badge')) return;
    const button = row.querySelector('.register-toggle');
    const open = button.getAttribute('aria-expanded') !== 'true';
    document.querySelectorAll('tr[data-register-row]').forEach(other => setOpen(other, false));
    setOpen(row, open);
  });
})();
"""
