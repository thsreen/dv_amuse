"""Bounded, read-only local repository scan for the interactive testplan flow."""
import os
import re
from pathlib import Path

SPEC_SUFFIXES = {".pdf", ".docx", ".md", ".html", ".htm", ".txt", ".rst"}
RTL_SUFFIXES = {".v", ".sv"}
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "build", "out", "runs",
             "verilog-backup", "backup", "bench", "sim", "syn", "lint", "fv"}
MODULE = re.compile(r"\bmodule\s+(?:automatic\s+)?([A-Za-z_][A-Za-z_0-9]*)\b")
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
    for token in re.findall(r"[^\s`'\"]+", prompt):
        token = token.strip(".,:;()[]{}")
        if not token or "://" in token or not (token.startswith(("/", ".", "~")) or "/" in token):
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


def inspect_repo(repo: Path) -> dict:
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
    for path in rtl:
        try:
            source = path.read_bytes()[:256_000].decode("utf-8", errors="replace")
        except OSError:
            continue
        for name in MODULE.findall(source):
            modules.append((name, path))
    tops = [(name, path) for name, path in modules if name.lower() == "top" or name.lower().endswith("_top")]
    top = tops[0] if len(tops) == 1 else None
    return dict(repo=repo, specs=specs, rtl_files=[p for p in rtl if any(p == m[1] for m in modules)],
                top=top[0] if top else "", top_file=top[1] if top else None,
                notes=(["No specification document found in doc/docs/spec directories."] if not specs else [])
                + (["Top RTL module could not be selected unambiguously."] if rtl and not top else []))
