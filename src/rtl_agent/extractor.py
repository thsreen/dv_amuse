"""Extract one configured module's port contract without reading its behavior as a spec.

This intentionally supports a bounded Verilog/SystemVerilog declaration subset. Unsupported
ports/types/constant expressions fail the entire extraction; no guessed widths or partial success.
"""
import math
import re
from pathlib import Path

from .constants import evaluate
from .source import IDENT, RESERVED, Preprocessor, RTLExtractionError, Token, bracket, spelling, split_at

VERSION = "declarations-v1"
DIRECTIONS = {"input", "output", "inout"}
QUALIFIERS = {"wire", "reg", "logic", "bit", "tri", "signed", "unsigned", "var"}


def _identifier(token: Token) -> str:
    if re.fullmatch(IDENT, token.text) is None or token.text in RESERVED:
        raise RTLExtractionError(f"{token.path}:{token.line}: unsupported identifier {token.text!r}")
    return token.text


def _dimension_tokens(tokens: list[Token], index: int) -> tuple[list[list[Token]], int]:
    dimensions = []
    while index < len(tokens) and tokens[index].text == "[":
        content, index = bracket(tokens, index, "[", "]")
        dimensions.append(content)
    return dimensions, index


def _ports(tokens: list[Token], inherited: dict | None = None) -> tuple[list[dict], dict]:
    """ANSI port list or a single non-ANSI declaration, preserving inherited types."""
    output = []
    current = inherited
    for group in split_at(tokens, ","):
        if not group:
            raise RTLExtractionError("empty port declaration")
        i = 0
        if group[0].text in DIRECTIONS:
            direction = group[0].text
            i = 1
            qualifiers = []
            while i < len(group) and group[i].text in QUALIFIERS:
                qualifiers.append(group[i].text)
                i += 1
            packed, i = _dimension_tokens(group, i)
            if "signed" in qualifiers and "unsigned" in qualifiers:
                raise RTLExtractionError("conflicting signedness in port declaration")
            kinds = set(qualifiers) & {"wire", "reg", "logic", "bit", "tri", "var"}
            if len(kinds & {"reg", "logic", "bit"}) > 1 or ("var" in kinds and kinds & {"wire", "tri"}):
                raise RTLExtractionError("conflicting port data types")
            if direction == "inout" and kinds & {"reg", "var"}:
                raise RTLExtractionError("inout port must be a net")
            current = dict(direction=direction, signed="signed" in qualifiers,
                           data_type="bit" if "bit" in qualifiers else "logic", packed_tokens=packed)
        if current is None or i >= len(group):
            raise RTLExtractionError(f"unsupported port declaration: {spelling(group)}")
        name = _identifier(group[i])
        evidence = group[i].evidence()
        i += 1
        unpacked, i = _dimension_tokens(group, i)
        if i != len(group):
            raise RTLExtractionError(f"unsupported port type/default/expression: {spelling(group)}")
        output.append(dict(current, name=name, unpacked_tokens=unpacked, source=evidence))
    return output, current


def _parameter_declarations(tokens: list[Token], *, local: bool = False) -> list[dict]:
    result = []
    integer_type = False
    for group in split_at(tokens, ","):
        if not group:
            raise RTLExtractionError("empty parameter declaration")
        eq = next((i for i, t in enumerate(group) if t.text == "="), -1)
        if eq < 1:
            raise RTLExtractionError(f"parameter needs a default: {spelling(group)}")
        name = _identifier(group[eq - 1])
        prefix = [t.text for t in group[:eq - 1]]
        if any(p not in ("parameter", "localparam", "integer", "int", "signed") for p in prefix):
            raise RTLExtractionError(f"unsupported parameter type: {spelling(group)}")
        if "parameter" in prefix or "localparam" in prefix:
            integer_type = False
        if "int" in prefix or "integer" in prefix:
            integer_type = True
        if not integer_type and any("'" in t.text for t in group[eq + 1:]):
            raise RTLExtractionError("sized untyped parameters require a compiler frontend (use integer parameters)")
        result.append(dict(name=name, expression=spelling(group[eq + 1:]), tokens=group[eq + 1:],
                           local=local, integer_type=integer_type, source=group[eq - 1].evidence()))
    return result


def _module(tokens: list[Token], top: str) -> tuple[list[Token], list[Token], list[dict], str]:
    found = []
    i = 0
    while i < len(tokens):
        if tokens[i].text != "module":
            i += 1
            continue
        i += 1
        if i < len(tokens) and tokens[i].text in ("automatic", "static"):
            i += 1
        if i >= len(tokens):
            raise RTLExtractionError("incomplete module declaration")
        name = tokens[i].text
        start = i + 1
        end = next((j for j in range(start, len(tokens)) if tokens[j].text == "endmodule"), None)
        if end is None:
            raise RTLExtractionError(f"module {name} has no endmodule")
        if name == top:
            header_end = next((j for j in range(start, end) if tokens[j].text == ";"), None)
            if header_end is None:
                raise RTLExtractionError(f"module {name} has no header terminator")
            found.append((tokens[start:header_end], tokens[header_end + 1:end], tokens[start - 1].path))
        i = end + 1
    if len(found) != 1:
        raise RTLExtractionError(f"expected exactly one module {top!r}, found {len(found)}; select explicit source files")
    header, body, top_source = found[0]
    parameters = []
    i = 0
    if header and header[0].text == "#":
        parameter_tokens, i = bracket(header, 1)
        parameters = _parameter_declarations(parameter_tokens)
    if i == len(header):
        ports = []
    else:
        ports, i = bracket(header, i)
        if i != len(header):
            raise RTLExtractionError("unsupported tokens after module port list")
    return ports, body, parameters, top_source


def _body_declarations(body: list[Token]) -> tuple[list[dict], list[dict], list[list[Token]]]:
    ports, parameters, redeclarations = [], [], []
    i = 0
    scopes = []
    while i < len(body):
        word = body[i].text
        # Function/task arguments are not module ports. Skip their whole scope.
        if word in ("function", "task"):
            endword = "end" + word
            end = next((j for j in range(i + 1, len(body)) if body[j].text == endword), None)
            if end is None:
                raise RTLExtractionError(f"unterminated {word}")
            i = end + 1
            continue
        if word in ("begin", "fork", "generate", "class"):
            scopes.append(word)
        elif word in ("end", "join", "join_any", "join_none", "endgenerate", "endclass"):
            if scopes:
                scopes.pop()
        if scopes:
            i += 1
            continue
        if word in DIRECTIONS | {"parameter", "localparam"}:
            end = next((j for j in range(i + 1, len(body)) if body[j].text == ";"), None)
            if end is None:
                raise RTLExtractionError("unterminated module declaration")
            if word in DIRECTIONS:
                declarations, _ = _ports(body[i:end])
                ports.extend(declarations)
            else:
                parameters.extend(_parameter_declarations(body[i:end], local=word == "localparam"))
            i = end + 1
        elif word in {"wire", "reg", "logic", "bit", "tri"}:
            end = next((j for j in range(i + 1, len(body)) if body[j].text == ";"), None)
            if end is None:
                raise RTLExtractionError("unterminated net/variable declaration")
            redeclarations.append(body[i:end])
            i = end + 1
        else:
            i += 1
    return ports, parameters, redeclarations


def _check_redeclarations(declarations: list[list[Token]], ports: list[dict], values: dict[str, int]) -> None:
    """Legacy separate reg/wire declarations must not silently alter a port's effective type."""
    by_name = {p["name"]: p for p in ports}
    for tokens in declarations:
        # Most declarations describe internal nets, which are outside the port contract.
        if not any(t.text in by_name for t in tokens):
            continue
        cleaned = []
        for group in split_at(tokens, ","):
            # Initialization expressions are not part of the declared shape.
            if cleaned:
                cleaned.append(Token(",", tokens[0].path, tokens[0].line, tokens[0].quote))
            cleaned += split_at(group, "=")[0]
        direction = Token("input", tokens[0].path, tokens[0].line, tokens[0].quote)
        nets, _ = _ports([direction] + cleaned)
        for net in nets:
            port = by_name.get(net["name"])
            if port is None:
                continue
            old = _resolve_dimensions(port["packed_tokens"], values, packed=True)
            new = _resolve_dimensions(net["packed_tokens"], values, packed=True)
            old_bounds = [(d["left"], d["right"]) for d in old]
            new_bounds = [(d["left"], d["right"]) for d in new]
            old_unpacked = _resolve_dimensions(port["unpacked_tokens"], values, packed=False)
            new_unpacked = _resolve_dimensions(net["unpacked_tokens"], values, packed=False)
            if (old_bounds != new_bounds or port["signed"] != net["signed"]
                    or port["data_type"] != net["data_type"]
                    or [(d["left"], d["right"]) for d in old_unpacked]
                    != [(d["left"], d["right"]) for d in new_unpacked]):
                raise RTLExtractionError(f"port {net['name']} has a differing net/variable redeclaration; "
                                         "declare its complete type on the input/output line")


def _resolve_dimensions(dimensions: list[list[Token]], values: dict[str, int], *, packed: bool) -> list[dict]:
    result = []
    for tokens in dimensions:
        parts = split_at(tokens, ":")
        if len(parts) == 2:
            left, right = [evaluate(p, values) for p in parts]
        elif len(parts) == 1 and not packed:
            size = evaluate(tokens, values)
            if size <= 0:
                raise RTLExtractionError("unpacked array size must be positive")
            left, right = 0, size - 1
        else:
            raise RTLExtractionError(f"unsupported dimension: [{spelling(tokens)}]")
        result.append(dict(expression=spelling(tokens), left=left, right=right, size=abs(left - right) + 1))
    return result


def extract_interface(files: list[Path], top: str, *, include_dirs: list[Path] | None = None,
                      defines: dict[str, str] | None = None, overrides: dict[str, str] | None = None) -> dict:
    """Read only explicit sources/includes and return one configured, source-backed port contract."""
    if re.fullmatch(IDENT, top) is None or top in RESERVED or not files or len(files) > 256:
        raise RTLExtractionError("provide a simple top module name and 1..256 explicit RTL source files")
    defines, overrides = defines or {}, overrides or {}
    if any(re.fullmatch(IDENT, n) is None for n in defines.keys() | overrides.keys()):
        raise RTLExtractionError("macro and parameter names must be simple identifiers")
    pp = Preprocessor(include_dirs or [], defines)
    tokens = []
    for file in files:
        tokens.extend(pp.read(file))
    header, body, parameters, top_source = _module(tokens, top)
    body_ports, body_parameters, redeclarations = _body_declarations(body)
    parameters.extend(body_parameters)
    names = [p["name"] for p in parameters]
    if len(set(names)) != len(names):
        raise RTLExtractionError("duplicate or scoped parameter declarations require a compiler frontend")
    allowed = {p["name"] for p in parameters if not p["local"]}
    if set(overrides) - allowed:
        raise RTLExtractionError(f"unknown or local parameter override: {sorted(set(overrides) - allowed)}")
    values: dict[str, int] = {}
    pending = list(parameters)
    # Resolve forward references as well as dependencies on overridden parameters.
    while pending:
        deferred = []
        for p in pending:
            expr = p["tokens"]
            if p["name"] in overrides:
                from .source import TOKEN
                expr = [Token(m[0], "<override>", 1, overrides[p["name"]])
                        for m in TOKEN.finditer(overrides[p["name"]])]
                if not p["integer_type"] and any("'" in t.text for t in expr):
                    raise RTLExtractionError("sized untyped parameter overrides require a compiler frontend")
            try:
                value = evaluate(expr, values)
            except RTLExtractionError:
                deferred.append(p)
                continue
            values[p["name"]] = value
        if len(deferred) == len(pending):
            p = deferred[0]
            raise RTLExtractionError(f"cannot resolve parameter {p['name']}: {overrides.get(p['name'], p['expression'])}")
        pending = deferred
    if not header:
        ports = []
        if body_ports:
            raise RTLExtractionError("port declarations exist outside an empty module header")
    elif header[0].text in DIRECTIONS:
        ports, _ = _ports(header)
        if body_ports:
            raise RTLExtractionError("mixed ANSI and non-ANSI port declarations")
    else:
        port_names = []
        for group in split_at(header, ","):
            if len(group) != 1:
                raise RTLExtractionError(f"unsupported non-ANSI port expression: {spelling(group)}")
            port_names.append(_identifier(group[0]))
        by_name = {p["name"]: p for p in body_ports}
        if len(by_name) != len(body_ports) or set(by_name) != set(port_names):
            raise RTLExtractionError("non-ANSI port declarations do not match the module header exactly")
        ports = [by_name[n] for n in port_names]
    if len({p["name"] for p in ports}) != len(ports):
        raise RTLExtractionError("duplicate module ports")
    _check_redeclarations(redeclarations, ports, values)
    output = []
    for port in ports:
        packed = _resolve_dimensions(port.pop("packed_tokens"), values, packed=True)
        unpacked = _resolve_dimensions(port.pop("unpacked_tokens"), values, packed=False)
        width = math.prod(d["size"] for d in packed)
        bits = width * math.prod(d["size"] for d in unpacked)
        if bits > 1_048_576:
            raise RTLExtractionError(f"port {port['name']} exceeds the 1048576-bit extraction budget")
        output.append(dict(port, packed_dimensions=packed, unpacked_dimensions=unpacked,
                           width_bits=width, total_bits=bits))
    return dict(schema_version=1, extractor=VERSION, status="PASS", authority="rtl_declarations",
                review_status="NEEDS_REVIEW", top=top, top_source=top_source,
                sources=[pp.files[p] for p in sorted(pp.files)],
                configuration=dict(files=[str(p.resolve()) for p in files],
                                   include_dirs=[str(p.resolve()) for p in include_dirs or []],
                                   defines=defines, parameter_overrides=overrides),
                parameters=[{k: v for k, v in p.items() if k != "tokens"} | {"value": values[p["name"]]}
                            for p in parameters], ports=output)
