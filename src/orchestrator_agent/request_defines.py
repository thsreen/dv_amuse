"""Turn configuration words in a request into RTL compile defines.

A request such as "use the 8 bit version" or "define DATA_BUS_WIDTH_8" selects a compile-time configuration of the RTL.
The macro names come only from the RTL sources (`ifdef/`ifndef/`define/`elsif), never from a design-specific table, so the
same rule works for any design. Anything that is not clearly resolved is returned as a question, never guessed.
"""
import re
from pathlib import Path

MACRO_RE = re.compile(r"`(?:ifdef|ifndef|elsif|define)\s+([A-Za-z_]\w*)")
WIDTH_RE = re.compile(r"\b(\d+)[\s-]*bit\b", re.IGNORECASE)
# A macro that selects a width names its bus or data path; a number alone (a FIFO trigger level, a register) is not one.
BUS_WORDS = ("WIDTH", "BUS", "DATA", "BITS")


def source_macros(files) -> list[str]:
    """Macro names the RTL sources test or define, in first-seen order."""
    seen = {}
    for path in files:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name in MACRO_RE.findall(text):
            seen.setdefault(name, None)
    return list(seen)


def resolve(request: str, files) -> tuple[list[str], str | None]:
    """(defines, blocking question). The question is set only when a width phrase matches several macros."""
    macros = source_macros(files)
    if not macros:
        return [], None
    defines = []
    for name in macros:  # a macro named outright in the request
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", request):
            defines.append(name)
    for match in WIDTH_RE.finditer(request):
        width = match.group(1)
        candidates = [m for m in macros if re.search(rf"(?:^|_){width}(?:_|$)", m) and m not in defines
                      and any(word in m.upper() for word in BUS_WORDS)]
        if not candidates:
            continue  # the RTL has no configuration macro for this width: nothing to select, nothing to block
        if len(candidates) > 1:
            return sorted(set(defines)), (f"The request says {width}-bit, which matches several RTL configuration macros "
                                          f"({', '.join(candidates)}). Name the one you want, for example 'define {candidates[0]}'.")
        defines.append(candidates[0])
    return sorted(set(defines)), None
