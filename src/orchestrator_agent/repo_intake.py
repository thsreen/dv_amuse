"""Bounded, read-only local repository scan for the interactive testplan flow."""
import os
import re
from pathlib import Path

SPEC_SUFFIXES = {".pdf", ".docx", ".md", ".html", ".htm", ".txt", ".rst"}
RTL_SUFFIXES = {".v", ".sv"}
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "build", "out", "runs",
             "verilog-backup", "backup", "bench", "sim", "syn", "lint", "fv"}
MODULE = re.compile(r"\bmodule\s+(?:automatic\s+)?([A-Za-z_][A-Za-z_0-9]*)\b")
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
TESTBENCH = re.compile(r"(^|_)(tb|test|testbench|bench)(_|$)|_tb$", re.I)
MAX_FILES = 512


def _files(repo: Path) -> list[Path]:
    found = []
    for root, dirs, names in os.walk(repo):
        base = Path(root)
        depth = len(base.relative_to(repo).parts)
        dirs[:] = [] if depth >= 6 else sorted(d for d in dirs if d.lower() not in SKIP_DIRS)
        for name in sorted(names):
            if Path(name).suffix.lower() in SPEC_SUFFIXES | RTL_SUFFIXES:
                found.append(base / name)
                if len(found) >= MAX_FILES:
                    return found
    return found


def find_repo(prompt: str, workspace: Path) -> Path | None:
    """Resolve an explicit local path or a uniquely named baseline repository."""
    for match in re.finditer(r'"([^"]+)"|\x27([^\x27]+)\x27|`([^`]+)`|([^\s]+)', prompt):
        token = next(value for value in match.groups() if value is not None)
        token = token.lstrip("([{ ").rstrip(",:;)]} ")
        if token.endswith(".") and token not in (".", ".."):
            token = token[:-1]
        if not token or "://" in token:
            continue
        if not ("/" in token or token.startswith((".", "~")) or token == prompt.strip()):
            continue
        path = Path(token).expanduser()
        for candidate in (path, workspace / path, workspace.parent / path):
            if candidate.is_dir() and candidate.resolve() != workspace.resolve():
                return candidate.resolve()
    baseline = workspace.parent / "baseline_repos"
    if not baseline.is_dir():
        return None
    candidates = [p for p in sorted(baseline.iterdir()) if p.is_dir() and not p.is_symlink()][:64]
    normalized = re.sub(r"[^a-z0-9]", "", prompt.lower())
    words = set(re.findall(r"[a-z0-9]{4,}", prompt.lower())) - {
        "make", "plan", "test", "tests", "testplan", "code", "generate", "verify", "verification",
        "design", "repository", "specification", "from", "with", "using", "build"}
    matched = [p for p in candidates if (name := re.sub(r"[^a-z0-9]", "", p.name.lower())) in normalized
               or any(word in name for word in words)]
    return matched[0].resolve() if len(matched) == 1 else None


def pick_top(sources: dict[str, str], hint: str = "", files: dict[str, Path] | None = None) -> tuple[str, list[str]]:
    """Choose the design root from {module name: source text}; return (top, notes).

    Roots are modules no other module instantiates. Testbench-named roots are set aside; among
    several roots the one reaching the most modules wins; ties go to a root the user's `hint` names,
    then a `top`-style name, then a root whose file is named after it. Returns an empty top with a
    note when still ambiguous, so the caller can ask the user.
    """
    names = set(sources)
    children: dict[str, set[str]] = {}
    for name, text in sources.items():
        body = COMMENTS.sub(" ", text)
        found = set()
        for other in names - {name}:
            if re.search(rf"(?<![\w$.]){re.escape(other)}\s*(?:#\s*\([^;]*?\)\s*)?[A-Za-z_]\w*\s*(?:\[[^\]]*\]\s*)?\(", body):
                found.add(other)
        children[name] = found
    instantiated = set().union(*children.values()) if children else set()
    roots = sorted(names - instantiated)
    if not roots:
        return "", ["Every RTL module is instantiated by another; no hierarchy root found."]
    designs = [r for r in roots if not TESTBENCH.search(r)] or roots

    def reach(name: str) -> int:
        seen, todo = set(), [name]
        while todo:
            for child in children.get(todo.pop(), ()):
                if child not in seen:
                    seen.add(child)
                    todo.append(child)
        return len(seen)

    if len(designs) == 1:
        return designs[0], []
    best = max(reach(r) for r in designs)
    widest = [r for r in designs if reach(r) == best]
    if len(widest) == 1:
        return widest[0], [f"Several uninstantiated modules ({', '.join(designs)}); chose {widest[0]} as it reaches the most modules."]
    words = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", hint))
    tiers = (("named in your request", lambda r: r in words),
             ("has a top-style name", lambda r: r.lower() == "top" or r.lower().endswith("_top")),
             ("lives in a file of the same name", lambda r: bool(files) and files.get(r) is not None
              and files[r].stem == r))
    for why, test in tiers:
        hit = [r for r in widest if test(r)]
        if len(hit) == 1:
            return hit[0], [f"Several equally wide roots ({', '.join(widest)}); chose {hit[0]}: {why}."]
        widest = hit or widest
    return "", [f"Top RTL module is ambiguous among: {', '.join(widest)}. Name it in your request."]


def inspect_repo(repo: Path, hint: str = "") -> dict:
    """Report source candidates and top module without writing or running a model."""
    repo = repo.resolve()
    if not repo.is_dir():
        raise ValueError(f"repository directory not found: {repo}")
    files = _files(repo)
    specs = [p for p in files if p.suffix.lower() in SPEC_SUFFIXES
             and not re.match(r"^(changes|changelog|history|license|licence|copying)\b", p.stem, re.I)
             and any(part.lower() in {"doc", "docs", "spec", "specs", "documentation"}
                     for part in p.relative_to(repo).parts[:-1])]
    rtl = [p for p in files if p.suffix.lower() in RTL_SUFFIXES]
    modules = []
    sources: dict[str, str] = {}
    for path in rtl:
        try:
            source = path.read_bytes()[:256_000].decode("utf-8", errors="replace")
        except OSError:
            continue
        stripped = COMMENTS.sub(" ", source)
        for match in MODULE.finditer(stripped):
            name = match.group(1)
            modules.append((name, path))
            end = stripped.find("endmodule", match.end())
            sources.setdefault(name, stripped[match.end():end if end >= 0 else None])
    where = {}
    for name, path in modules:
        where.setdefault(name, path)
    top, top_notes = pick_top(sources, hint, where)
    top_file = where.get(top)
    return dict(repo=repo, specs=specs, rtl_files=[p for p in rtl if any(p == m[1] for m in modules)],
                top=top, top_file=top_file,
                notes=(["No specification document found in doc/docs/spec directories."] if not specs else [])
                + (top_notes if rtl else []))
