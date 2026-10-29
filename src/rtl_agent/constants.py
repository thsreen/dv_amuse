"""Small, safe integer-expression subset used only to resolve declaration bounds."""
import re

from .source import RTLExtractionError, Token, spelling


# SystemVerilog precedence, deliberately independent of Python's expression grammar.
PRECEDENCE = {"||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6,
              "<": 7, "<=": 7, ">": 7, ">=": 7, "<<": 8, ">>": 8,
              "+": 9, "-": 9, "*": 10, "/": 10, "%": 10}


def evaluate(tokens: list[Token], values: dict[str, int]) -> int:
    """Evaluate non-overflowing signed 32-bit integer expressions; never execute source."""
    if not tokens or len(tokens) > 256:
        raise RTLExtractionError("empty or over-budget constant expression")
    words = [t.text for t in tokens]
    # Sized arithmetic has context-dependent width/sign rules. Refuse instead of using Python rules.
    if len(words) > 1 and any("'" in w for w in words):
        raise RTLExtractionError(f"sized-literal arithmetic requires a compiler frontend: {spelling(tokens)}")
    pos = 0

    def bounded(value: int) -> int:
        if not -(2 ** 31) <= value < 2 ** 31:
            raise RTLExtractionError("constant exceeds the supported signed 32-bit range")
        return value

    def atom() -> int:
        nonlocal pos
        if pos >= len(words):
            raise RTLExtractionError("incomplete constant expression")
        word = words[pos]
        pos += 1
        if word in ("+", "-", "~", "!"):
            value = atom()
            return bounded({"+": lambda: value, "-": lambda: -value,
                            "~": lambda: ~value, "!": lambda: int(not value)}[word]())
        if word == "(":
            value = expr(0)
            expect(")")
            return value
        if word == "$clog2":
            expect("(")
            value = expr(0)
            expect(")")
            if value < 0:
                raise RTLExtractionError("negative $clog2 argument")
            return max(0, (value - 1).bit_length()) if value else 0
        if word in values:
            return values[word]
        if re.fullmatch(r"\d[\d_]*", word):
            if len(word) > 64:
                raise RTLExtractionError("over-budget integer literal")
            return bounded(int(word.replace("_", "")))
        literal = re.fullmatch(r"(\d[\d_]*)?'([sS]?)([bBoOdDhH])([0-9a-fA-F_]+)", word)
        if literal:
            width, signed, base, digits = literal.groups()
            if width and len(width.replace("_", "")) > 2:
                raise RTLExtractionError("literal width exceeds supported 32-bit constants")
            bits = int(width.replace("_", "")) if width else 32
            if not 1 <= bits <= 32 or len(digits) > 128:
                raise RTLExtractionError("literal width exceeds supported 32-bit constants")
            try:
                value = int(digits.replace("_", ""), {"b": 2, "o": 8, "d": 10, "h": 16}[base.lower()])
            except ValueError as exc:
                raise RTLExtractionError(f"invalid integer literal: {word}") from exc
            value &= (1 << bits) - 1
            if signed and value & (1 << (bits - 1)):
                value -= 1 << bits
            return bounded(value)
        if word in ("'0", "'1"):
            # '1 is context sized and cannot be resolved as a standalone width/parameter.
            if word == "'1":
                raise RTLExtractionError("context-sized '1 requires a compiler frontend")
            return 0
        raise RTLExtractionError(f"unresolved or unsupported constant: {word}")

    def expect(word: str) -> None:
        nonlocal pos
        if pos >= len(words) or words[pos] != word:
            raise RTLExtractionError(f"expected {word} in constant expression")
        pos += 1

    def expr(minimum: int) -> int:
        nonlocal pos
        left = atom()
        while pos < len(words) and PRECEDENCE.get(words[pos], -1) >= minimum:
            op = words[pos]
            level = PRECEDENCE[op]
            pos += 1
            right = expr(level + 1)
            if op in ("<<", ">>") and not 0 <= right <= 31:
                raise RTLExtractionError("shift exceeds supported range 0..31")
            if op == ">>" and left < 0:
                raise RTLExtractionError("logical shift of negative value requires a compiler frontend")
            if op in ("/", "%") and right == 0:
                raise RTLExtractionError("division by zero in constant expression")
            quotient = (abs(left) // abs(right)) * (-1 if (left < 0) != (right < 0) else 1) if right else 0
            left = bounded({
                "+": lambda: left + right, "-": lambda: left - right, "*": lambda: left * right,
                "/": lambda: quotient, "%": lambda: left - quotient * right,
                "<<": lambda: left << right, ">>": lambda: left >> right,
                "&": lambda: left & right, "|": lambda: left | right, "^": lambda: left ^ right,
                "<": lambda: int(left < right), "<=": lambda: int(left <= right),
                ">": lambda: int(left > right), ">=": lambda: int(left >= right),
                "==": lambda: int(left == right), "!=": lambda: int(left != right),
                "&&": lambda: int(bool(left) and bool(right)), "||": lambda: int(bool(left) or bool(right)),
            }[op]())
        return left

    value = expr(0)
    if pos != len(words):
        raise RTLExtractionError(f"unsupported constant expression: {spelling(tokens)}")
    return value
