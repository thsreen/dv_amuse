"""Bounded preprocessing and tokenization for declaration extraction (not a compiler)."""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


class RTLExtractionError(ValueError):
    """Input cannot be extracted faithfully by the supported declaration subset."""


IDENT = r"[a-zA-Z_][a-zA-Z0-9_$]*"
RESERVED = set("""accept_on alias always always_comb always_ff always_latch and assert assign assume
automatic before begin bind bins binsof bit break buf bufif0 bufif1 byte case casex casez cell chandle
checker class clocking cmos config const constraint context continue cover covergroup coverpoint cross
deassign default defparam design disable dist do edge else end endcase endchecker endclass endclocking
endconfig endfunction endgenerate endgroup endinterface endmodule endpackage endprimitive endprogram
endproperty endsequence endspecify endtable endtask enum event eventually expect export extends extern
final first_match for force foreach forever fork forkjoin function generate genvar global highz0 highz1
if iff ifnone ignore_bins illegal_bins implements implies import incdir include initial inout input
inside int integer interconnect interface intersect join join_any join_none large let liblist library
local localparam logic longint macromodule matches medium modport module nand negedge nettype new nexttime
nmos nor noshowcancelled not notif0 notif1 null or output package packed parameter pmos posedge primitive
priority program property protected pull0 pull1 pulldown pullup pulsestyle_ondetect pulsestyle_onevent
pure rand randc randcase randsequence rcmos real realtime ref reg reject_on release repeat restrict return
rnmos rpmos rtran rtranif0 rtranif1 s_always s_eventually s_nexttime s_until s_until_with scalared sequence
shortint shortreal showcancelled signed small solve soft specify specparam static string strong strong0
strong1 struct super supply0 supply1 sync_accept_on sync_reject_on table tagged task this throughout time
timeprecision timeunit tran tranif0 tranif1 tri tri0 tri1 triand trior trireg type typedef union unique
unique0 unsigned until until_with untyped use uwire var vectored virtual void wait wait_order wand weak
weak0 weak1 while wildcard wire with within wor xnor xor""".split())
TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"|\\[^\s]+|'
    r"(?:\d[\d_]*\s*)?'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|'[01xXzZ]|"
    r"\d[\d_]*|\$?[a-zA-Z_][a-zA-Z0-9_$]*|"
    r"\*\*|<<<|>>>|<<|>>|<=|>=|==|!=|&&|\|\||::|[^\s]"
)


@dataclass(frozen=True)
class Token:
    text: str
    path: str
    line: int
    quote: str

    def evidence(self) -> dict:
        return dict(path=self.path, line=self.line, quote=self.quote, status="DOCUMENTED")


def strip_comments(text: str) -> str:
    """Replace comments with spaces, retaining all line numbers and string literals."""
    pattern = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.S)
    return pattern.sub(lambda m: m[0] if m[0].startswith('"') else
                       re.sub(r"[^\n]", " ", m[0]), text)


class Preprocessor:
    def __init__(self, include_dirs: list[Path], defines: dict[str, str]):
        self.include_dirs = [p.resolve() for p in include_dirs]
        self.macros = dict(defines)
        self.files: dict[str, dict] = {}
        self.total_bytes = 0
        self.token_count = 0
        self.expansions = 0

    def _expand(self, text: str, stack: tuple[str, ...] = ()) -> str:
        # Strings are data; macro names inside them must stay untouched.
        pattern = re.compile(r'"(?:\\.|[^"\\])*"|`(' + IDENT + r")")

        def replace(m: re.Match) -> str:
            name = m[1]
            if name is None:
                return m[0]
            self.expansions += 1
            if self.expansions > 250_000:
                raise RTLExtractionError("macro expansion exceeds the 250000-substitution budget")
            if name in stack or len(stack) >= 32:
                raise RTLExtractionError(f"recursive macro expansion: {name}")
            if name not in self.macros:
                raise RTLExtractionError(f"undefined macro: `{name}")
            value = self.macros[name]
            if value.startswith("<function-macro>"):
                raise RTLExtractionError(f"function-like macro `{name} requires a full compiler frontend")
            return self._expand(value, stack + (name,))

        pieces = []
        offset, length = 0, 0
        for match in pattern.finditer(text):
            prefix, replacement = text[offset:match.start()], replace(match)
            length += len(prefix) + len(replacement)
            if length > 8 * 1024 * 1024:
                raise RTLExtractionError("expanded line exceeds the 8 MiB extraction budget")
            pieces.extend((prefix, replacement))
            offset = match.end()
        tail = text[offset:]
        if length + len(tail) > 8 * 1024 * 1024:
            raise RTLExtractionError("expanded line exceeds the 8 MiB extraction budget")
        return "".join(pieces) + tail

    def read(self, path: Path, stack: tuple[Path, ...] = ()) -> list[Token]:
        path = path.resolve()
        if path in stack or len(stack) >= 32:
            raise RTLExtractionError(f"recursive include or include depth exceeded: {path}")
        try:
            size = path.stat().st_size
            self.total_bytes += size
            if self.total_bytes > 8 * 1024 * 1024:
                raise RTLExtractionError("RTL input exceeds the 8 MiB extraction budget")
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise RTLExtractionError(f"cannot read RTL source {path}: {exc}") from exc
        self.files[str(path)] = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
        original = text.splitlines()
        lines = strip_comments(text).splitlines()
        frames: list[dict] = []
        tokens: list[Token] = []
        i = 0
        while i < len(lines):
            number = i + 1
            line = lines[i]
            while line.rstrip().endswith("\\"):
                i += 1
                if i >= len(lines):
                    raise RTLExtractionError(f"{path}:{number}: unfinished continuation")
                line = line.rstrip()[:-1] + " " + lines[i]
            i += 1
            active = all(f["active"] for f in frames)
            directive = re.match(r"\s*`(" + IDENT + r")\b(.*)", line)
            if directive:
                kind, rest = directive.groups()
                rest = rest.strip()
                if kind in ("ifdef", "ifndef", "elsif", "undef") and re.fullmatch(IDENT, rest) is None:
                    raise RTLExtractionError(f"{path}:{number}: `{kind} requires one macro name")
                if kind in ("else", "endif") and rest:
                    raise RTLExtractionError(f"{path}:{number}: unexpected text after `{kind}")
                if kind in ("ifdef", "ifndef"):
                    condition = rest in self.macros
                    if kind == "ifndef":
                        condition = not condition
                    frames.append(dict(parent=active, active=active and condition, taken=condition, otherwise=False))
                    continue
                if kind in ("else", "elsif", "endif"):
                    if not frames:
                        raise RTLExtractionError(f"{path}:{number}: unmatched `{kind}")
                    f = frames[-1]
                    if f["otherwise"]:
                        if kind != "endif":
                            raise RTLExtractionError(f"{path}:{number}: directive after `else")
                    if kind == "endif":
                        frames.pop()
                    else:
                        condition = kind == "else" or rest in self.macros
                        f["active"] = f["parent"] and not f["taken"] and condition
                        f["taken"] |= condition
                        f["otherwise"] = kind == "else"
                    continue
                if not active:
                    continue
                if kind == "include":
                    match = re.fullmatch(r'"([^"\n]+)"', self._expand(rest))
                    if match is None:
                        raise RTLExtractionError(f"{path}:{number}: unsupported include: {rest}")
                    candidates = [path.parent / match[1]] + [d / match[1] for d in self.include_dirs]
                    target = next((p for p in candidates if p.is_file()), None)
                    if target is None:
                        raise RTLExtractionError(f"{path}:{number}: include not found: {match[1]}")
                    tokens.extend(self.read(target, stack + (path,)))
                    continue
                if kind == "define":
                    match = re.match(r"(" + IDENT + r")(.*)", rest)
                    if match is None:
                        raise RTLExtractionError(f"{path}:{number}: malformed `define")
                    name, value = match.groups()
                    self.macros[name] = "<function-macro>" + value if value.startswith("(") else value.strip()
                    continue
                if kind == "undef":
                    self.macros.pop(rest, None)
                    continue
                if kind in ("timescale", "default_nettype", "resetall", "celldefine", "endcelldefine"):
                    continue
            if active:
                expanded = self._expand(line)
                found = [Token(m[0], str(path), number, original[number - 1]) for m in TOKEN.finditer(expanded)]
                self.token_count += len(found)
                if self.token_count > 250_000:
                    raise RTLExtractionError("RTL input exceeds the 250000-token extraction budget")
                tokens.extend(found)
        if frames:
            raise RTLExtractionError(f"{path}: unterminated conditional directive")
        return tokens


def spelling(tokens: list[Token]) -> str:
    return " ".join(t.text for t in tokens)


def split_at(tokens: list[Token], separator: str) -> list[list[Token]]:
    """Split only at the current bracket depth; reject unbalanced delimiters."""
    groups: list[list[Token]] = [[]]
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for token in tokens:
        t = token.text
        if t in pairs:
            if not stack or stack.pop() != pairs[t]:
                raise RTLExtractionError(f"{token.path}:{token.line}: unbalanced delimiter {t}")
        if t == separator and not stack:
            groups.append([])
        else:
            groups[-1].append(token)
        if t in ("(", "[", "{"):
            stack.append(t)
    if stack:
        raise RTLExtractionError("unbalanced declaration delimiters")
    return groups


def bracket(tokens: list[Token], index: int, opening: str = "(", closing: str = ")") -> tuple[list[Token], int]:
    if index >= len(tokens) or tokens[index].text != opening:
        raise RTLExtractionError(f"expected {opening} in declaration")
    depth = 1
    start = index + 1
    for i in range(start, len(tokens)):
        if tokens[i].text == opening:
            depth += 1
        elif tokens[i].text == closing:
            depth -= 1
            if depth == 0:
                return tokens[start:i], i + 1
    raise RTLExtractionError(f"unclosed {opening} in declaration")
