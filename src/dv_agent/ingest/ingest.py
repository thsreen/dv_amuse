"""Discover spec documents in a design repository and split them into citable L1 chunks."""
import bisect
import hashlib
import os
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
from html.parser import HTMLParser
from pathlib import Path

from ..core.fsutil import atomic_write_text
from ..core.models import Chunk, Manifest, SourceDoc

DOC_KINDS = {".pdf": "pdf", ".docx": "docx", ".md": "markdown", ".html": "html",
             ".htm": "html", ".txt": "text", ".rst": "text", ".doc": "doc"}
# Lower rank wins when the same document exists in several formats.
FORMAT_RANK = {"pdf": 0, "docx": 1, "markdown": 2, "html": 3, "text": 4, "doc": 5}
SUPPORTED = {"pdf", "markdown", "text", "docx", "html"}
DOC_DIRS = {"doc", "docs", "documentation", "spec", "specs", "specification"}
# Design-source, testbench and tool-output trees are not specification sources.
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "rtl", "src_rtl", "hdl",
             "bench", "tb", "sim", "syn", "lint", "fv", "out", "log", "logs", "build", "run"}
NON_SPEC_NAMES = re.compile(r"^(changes|changelog|history|license|licence|copying|authors|news)\b", re.I)


@dataclass
class ChunkConfig:
    max_chars: int = 2000
    min_chars: int = 400
    min_content_chars: int = 20


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _repo_revision(repo: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def discover(repo: Path, include: list[str] | None = None) -> list[SourceDoc]:
    """List candidate spec documents; everything not ingested gets a SKIPPED reason."""
    repo = repo.resolve()
    found: list[tuple[Path, str]] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP_DIRS)  # prune before descending
        for name in files:
            suffix = Path(name).suffix.lower()
            if suffix in DOC_KINDS:
                found.append((Path(root) / name, DOC_KINDS[suffix]))
    found.sort(key=lambda f: f[0].relative_to(repo).as_posix())

    docs: list[SourceDoc] = []
    for path, kind in found:
        rel = path.relative_to(repo).as_posix()
        raw = path.read_bytes()
        sha = _sha256(raw)
        authority = ("RTL_INFERRED" if kind == "markdown" and
                     (path.name == "rtl_derived_spec.md" or
                      raw.startswith(b"<!-- rtl-derived-spec: INFERRED;")) else "DOCUMENTED")
        docs.append(SourceDoc(doc_id=f"DOC-{sha[:12]}", path=rel, kind=kind, sha256=sha,
                              status="INGESTED", authority=authority))

    if include:
        for d in docs:
            if not any(fnmatch(d.path, pat) for pat in include):
                d.status, d.reason = "SKIPPED", "not matched by --include"
    else:
        in_doc_dir = [d for d in docs if any(p.lower() in DOC_DIRS for p in Path(d.path).parts[:-1])]
        preferred = {d.path for d in in_doc_dir} if in_doc_dir else None
        for d in docs:
            if preferred is not None and d.path not in preferred:
                d.status, d.reason = "SKIPPED", "outside documentation directories"
            elif NON_SPEC_NAMES.match(Path(d.path).name):
                d.status, d.reason = "SKIPPED", "changelog/license file, not a specification"

    seen_sha: dict[str, str] = {}
    by_stem: dict[str, list[SourceDoc]] = {}
    for d in docs:
        if d.status != "INGESTED":
            continue
        if d.sha256 in seen_sha:
            d.status, d.reason = "SKIPPED", f"identical content to {seen_sha[d.sha256]}"
            continue
        seen_sha[d.sha256] = d.path
        by_stem.setdefault(Path(d.path).stem.lower(), []).append(d)
    for group in by_stem.values():
        group.sort(key=lambda d: (FORMAT_RANK[d.kind], d.path))
        for d in group[1:]:
            d.status, d.reason = "SKIPPED", f"same document as {group[0].path} in a preferred format"

    for d in docs:
        if d.status == "INGESTED" and d.kind not in SUPPORTED:
            d.status, d.reason = "SKIPPED", f"no extractor for format '{d.kind}' yet"
    return docs


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PAGE_BREAK = object()


def _docx_heading_level(p: ET.Element) -> int | None:
    ppr = p.find(f"{W_NS}pPr")
    if ppr is None:
        return None
    outline = ppr.find(f"{W_NS}outlineLvl")
    if outline is not None and outline.get(f"{W_NS}val", "").isdigit():
        return int(outline.get(f"{W_NS}val")) + 1
    style = ppr.find(f"{W_NS}pStyle")
    m = re.match(r"^heading\s*(\d)$", style.get(f"{W_NS}val", "") if style is not None else "", re.I)
    return int(m.group(1)) if m else None


def _docx_runs(p: ET.Element) -> list:
    """Paragraph text pieces in order, with PAGE_BREAK markers for rendered or explicit page breaks."""
    out: list = []
    for el in p.iter():
        tag = el.tag
        if tag == f"{W_NS}t":
            out.append(el.text or "")
        elif tag == f"{W_NS}tab":
            out.append(" ")
        elif tag == f"{W_NS}lastRenderedPageBreak":
            out.append(PAGE_BREAK)
        elif tag == f"{W_NS}br":
            out.append(PAGE_BREAK if el.get(f"{W_NS}type") == "page" else "\n")
    return out


def _docx_pages(path: Path) -> tuple[list[str], str]:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W_NS}body")
    pages: list[list[str]] = [[]]
    has_heading = False

    def add_paragraph(p: ET.Element, prefix: str = "") -> None:
        line = prefix
        for piece in _docx_runs(p):
            if piece is PAGE_BREAK:
                if line.strip():
                    pages[-1].append(line.rstrip())
                line = prefix if prefix.startswith("#") else ""
                if pages[-1]:
                    pages.append([])
            else:
                line += piece
        if line.strip() and line.strip() != prefix.strip():
            pages[-1].append(line.rstrip())
        elif not prefix:
            pages[-1].append("")

    for el in list(body) if body is not None else []:
        if el.tag == f"{W_NS}p":
            level = _docx_heading_level(el)
            if level:
                has_heading = True
                add_paragraph(el, "#" * min(level, 6) + " ")
            else:
                add_paragraph(el)
        elif el.tag == f"{W_NS}tbl":
            for tr in el.iter(f"{W_NS}tr"):
                cells = [" ".join("".join(x for x in _docx_runs(cp) if x is not PAGE_BREAK).strip()
                                  for cp in tc.iter(f"{W_NS}p")).strip()
                         for tc in tr.findall(f"{W_NS}tc")]
                if any(cells):
                    pages[-1].append(" | ".join(cells))
            pages[-1].append("")
    return ["\n".join(lines) for lines in pages if any(x.strip() for x in lines)] or [""], (
        "markdown" if has_heading else "numbered")


class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "head", "noscript", "template"}
    BLOCK = {"p", "div", "li", "ul", "ol", "section", "article", "table", "pre", "dt", "dd", "caption",
             "blockquote", "header", "footer", "main", "figure", "figcaption", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.cur: list[str] = []
        self.row: list[str] | None = None
        self.skip_depth = 0
        self.heading: int | None = None
        self.has_heading = False
        self.pre = 0

    def _flush(self) -> None:
        text = "".join(self.cur)
        text = text if self.pre else re.sub(r"\s+", " ", text)
        if text.strip():
            prefix = "#" * self.heading + " " if self.heading else ""
            self.lines.append(prefix + text.strip())
        self.cur = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.heading = int(tag[1])
            self.has_heading = True
        elif tag == "tr":
            self._flush()
            self.row = []
        elif tag in ("td", "th"):
            self.cur = []
        elif tag == "br":
            self._flush()
        elif tag in self.BLOCK:
            self._flush()
            self.pre += tag == "pre"

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.heading = None
        elif tag in ("td", "th") and self.row is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cur)).strip())
            self.cur = []
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.lines.append(" | ".join(self.row))
            self.row = None
        elif tag in self.BLOCK:
            self._flush()
            if tag == "pre":
                self.pre = max(0, self.pre - 1)
            if tag in ("p", "table", "pre", "ul", "ol"):
                self.lines.append("")

    def handle_data(self, data):
        if not self.skip_depth:
            self.cur.append(data)


def _html_pages(path: Path) -> tuple[list[str], str]:
    parser = _HTMLText()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    parser.close()
    parser._flush()
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(parser.lines)).strip()
    return [text], "markdown" if parser.has_heading else "numbered"


def extract_document(path: Path, kind: str) -> tuple[list[str], str]:
    """Pages of text plus the heading mode ("markdown" or "numbered") for section detection."""
    if kind == "pdf":
        from pypdf import PdfReader
        return [page.extract_text() or "" for page in PdfReader(str(path)).pages], "numbered"
    if kind == "docx":
        return _docx_pages(path)
    if kind == "html":
        return _html_pages(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.split("\f"), "markdown" if kind == "markdown" else "numbered"


def _edge_key(line: str) -> str:
    key = re.sub(r"\d+", "#", line.strip())
    key = re.sub(r"\b[ivxlc]+\b", "#", key, flags=re.I)
    return re.sub(r"\s+", " ", key)


def clean_pages(pages: list[str], edge_lines: int = 3) -> list[str]:
    """Strip right whitespace and drop running headers/footers that repeat across pages."""
    split = [[ln.rstrip() for ln in p.splitlines()] for p in pages]
    if len(split) < 3:
        return ["\n".join(lines) for lines in split]

    def edges(lines: list[str]) -> list[int]:
        idx = [i for i, ln in enumerate(lines) if ln.strip()]
        return sorted(set(idx[:edge_lines] + idx[-edge_lines:]))

    counts = Counter()
    for lines in split:
        counts.update({_edge_key(lines[i]) for i in edges(lines)})
    threshold = max(2, len(split) // 2)
    repeated = {k for k, c in counts.items() if c >= threshold}
    cleaned = []
    for lines in split:
        drop = {i for i in edges(lines) if _edge_key(lines[i]) in repeated}
        cleaned.append("\n".join(ln for i, ln in enumerate(lines) if i not in drop))
    return cleaned


NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
NUMBER_ONLY = re.compile(r"^(\d+(?:\.\d+)*)\.?$")
MARKDOWN = re.compile(r"^(#{1,6})\s+(\S.*?)\s*#*$")
TOC_LEADER = re.compile(r"(\.{4,}|…{2,}|(\.\s){4,})")


def _title_like(text: str) -> bool:
    text = text.strip()
    if not (1 <= len(text) <= 90) or not text[0].isalpha() or TOC_LEADER.search(text):
        return False
    visible = [c for c in text if not c.isspace()]
    return sum(c.isalpha() for c in visible) / len(visible) >= 0.6 and not text.endswith((".", ",", ";"))


def _is_successor(last: tuple[int, ...], cand: tuple[int, ...]) -> bool:
    if not last:
        return cand in {(1,), (1, 1)}
    if cand == last + (1,):
        return True
    return any(cand == last[:k] + (last[k] + 1,) for k in range(len(last)))


@dataclass
class Heading:
    number: str
    title: str
    depth: int
    start: int  # char offset of the heading line


def find_headings(text: str, kind: str) -> list[Heading]:
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln))
    headings: list[Heading] = []
    last: tuple[int, ...] = ()
    counters: list[int] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or TOC_LEADER.search(line):
            continue
        if kind == "markdown":
            m = MARKDOWN.match(line)
            if m:
                title = m.group(2)
                numbered = NUMBERED.match(title)
                if numbered and _title_like(numbered.group(2)):
                    # Keep the document's own numbering ("4.3 Interrupt ...") instead of synthesizing one.
                    counters = [int(x) for x in numbered.group(1).split(".")]
                    title = numbered.group(2).strip()
                else:
                    depth = len(m.group(1))
                    counters = (counters + [0] * depth)[:depth]
                    counters[-1] += 1
                headings.append(Heading(".".join(map(str, counters)), title, len(counters), offsets[i]))
            continue
        number, title = None, None
        m = NUMBERED.match(line)
        if m and _title_like(m.group(2)):
            number, title = m.group(1), m.group(2).strip()
        elif NUMBER_ONLY.match(line):
            nxt = next((ln.strip() for ln in lines[i + 1:i + 4] if ln.strip()), "")
            if _title_like(nxt):
                number, title = NUMBER_ONLY.match(line).group(1), nxt
        if number is None:
            continue
        cand = tuple(int(p) for p in number.split("."))
        if _is_successor(last, cand):
            headings.append(Heading(number, title, len(cand), offsets[i]))
            last = cand
    return headings


def _cut_points(text: str, start: int, end: int) -> tuple[list[int], list[int]]:
    paras = [m.end() for m in re.finditer(r"\n[ \t]*\n", text[start:end])]
    lines = [m.end() for m in re.finditer(r"\n", text[start:end])]
    return [start + p for p in paras], [start + p for p in lines]


def _split_section(text: str, start: int, end: int, cfg: ChunkConfig) -> list[tuple[int, int]]:
    spans = []
    paras, lines = _cut_points(text, start, end)
    pos = start
    while end - pos > cfg.max_chars:
        limit = pos + cfg.max_chars
        floor = pos + cfg.min_chars
        cut = (max((p for p in paras if floor <= p <= limit), default=None)
               or max((p for p in lines if floor <= p <= limit), default=None)
               or limit)
        spans.append((pos, cut))
        pos = cut
    spans.append((pos, end))
    return spans


def chunk_document(doc: SourceDoc, text: str, kind: str, cfg: ChunkConfig) -> list[Chunk]:
    headings = find_headings(text, kind)
    bounds = [Heading("", "Front matter", 0, 0)] + headings
    if headings and headings[0].start == 0:
        bounds = headings
    chunks: list[Chunk] = []
    stack: list[Heading] = []
    for idx, h in enumerate(bounds):
        end = bounds[idx + 1].start if idx + 1 < len(bounds) else len(text)
        while stack and (stack[-1].depth >= h.depth or stack[-1].depth == 0):
            stack.pop()
        stack.append(h)
        path = [f"{s.number} {s.title}".strip() for s in stack]
        for c_start, c_end in _split_section(text, h.start, end, cfg):
            body = text[c_start:c_end]
            if len(body.strip()) < cfg.min_content_chars:
                continue
            page_start = bisect.bisect_right(doc.page_offsets, c_start)
            page_end = bisect.bisect_right(doc.page_offsets, max(c_start, c_end - 1))
            key = f"{doc.doc_id}|{h.number}|{c_start}"
            chunks.append(Chunk(
                chunk_id=f"CH-{_sha256(key.encode())[:10]}", doc_id=doc.doc_id, doc_path=doc.path,
                section_number=h.number, section_title=h.title, section_path=path,
                page_start=page_start, page_end=page_end, char_start=c_start, char_end=c_end,
                text=body, text_sha256=_sha256(body.encode())))
    return chunks


def ingest(repo: Path, out: Path, include: list[str] | None = None,
           cfg: ChunkConfig | None = None) -> tuple[Manifest, list[Chunk]]:
    cfg = cfg or ChunkConfig()
    repo = repo.resolve()
    docs = discover(repo, include)
    (out / "text").mkdir(parents=True, exist_ok=True)
    chunks: list[Chunk] = []
    for doc in docs:
        if doc.status != "INGESTED":
            continue
        try:
            raw_pages, heading_mode = extract_document(repo / doc.path, doc.kind)
            pages = clean_pages(raw_pages)
        except Exception as exc:  # extractor failures are recorded, not fatal
            doc.status, doc.reason = "FAILED", f"extraction error: {type(exc).__name__}"
            continue
        offsets, parts, pos = [], [], 0
        for page in pages:
            offsets.append(pos)
            parts.append(page + "\n")
            pos += len(page) + 1
        text = "".join(parts)
        doc.pages, doc.page_offsets = len(pages), offsets
        doc.text_path = f"text/{doc.doc_id}.txt"
        atomic_write_text(out / doc.text_path, text)
        doc_chunks = chunk_document(doc, text, heading_mode, cfg)
        for chunk in doc_chunks:
            chunk.authority = doc.authority
        if not doc_chunks:
            doc.status, doc.reason = "FAILED", "no extractable text"
        chunks.extend(doc_chunks)
    manifest = Manifest(repo=str(repo), repo_revision=_repo_revision(repo),
                        created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        include=include, documents=docs,
                        source_authority=("RTL_INFERRED" if any(d.status == "INGESTED" and d.authority == "RTL_INFERRED"
                                                                for d in docs) else "DOCUMENTED"))
    atomic_write_text(out / "chunks.jsonl", "".join(c.model_dump_json() + "\n" for c in chunks))
    atomic_write_text(out / "manifest.json", manifest.model_dump_json(indent=2))
    return manifest, chunks


def load_chunks(out: Path) -> list[Chunk]:
    with (out / "chunks.jsonl").open(encoding="utf-8") as fh:
        return [Chunk.model_validate_json(line) for line in fh if line.strip()]


def load_manifest(out: Path) -> Manifest:
    return Manifest.model_validate_json((out / "manifest.json").read_text(encoding="utf-8"))
