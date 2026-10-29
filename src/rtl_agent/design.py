"""Bounded static RTL analysis. This is a source parser, not HDL elaboration."""
import re
from dataclasses import dataclass, field

from .extractor import _ports
from .source import IDENT, RESERVED, RTLExtractionError, Token, bracket, spelling, split_at


@dataclass
class Statement:
    kind: str
    tokens: list[Token]
    condition: list[Token] = field(default_factory=list)
    children: list["Statement"] = field(default_factory=list)


def has_local_declarations(node: Statement) -> bool:
    kinds = {"reg", "wire", "logic", "bit", "int", "integer", "automatic", "static"}
    return ((node.kind == "simple" and bool(node.tokens) and node.tokens[0].text in kinds)
            or (node.kind == "loop" and any(t.text in kinds for t in node.condition))
            or any(has_local_declarations(child) for child in node.children))


def identifiers(tokens: list[Token]) -> list[str]:
    return sorted({t.text for t in tokens if re.fullmatch(IDENT, t.text) and t.text not in RESERVED})


def until_semicolon(tokens: list[Token], start: int) -> tuple[list[Token], int]:
    depth = 0
    for i in range(start, len(tokens)):
        word = tokens[i].text
        if word in ("(", "[", "{"):
            depth += 1
        elif word in (")", "]", "}"):
            depth -= 1
        elif word == ";" and depth == 0:
            return tokens[start:i], i + 1
    raise RTLExtractionError("unterminated RTL statement")


def statement(tokens: list[Token], start: int, depth: int = 0) -> tuple[Statement, int]:
    if depth > 100 or start >= len(tokens):
        raise RTLExtractionError("incomplete statement or nesting exceeds 100")
    word = tokens[start].text
    i = start + 1
    if word == "begin":
        if i < len(tokens) and tokens[i].text == ":":
            i += 2
        children = []
        while i < len(tokens) and tokens[i].text != "end":
            child, i = statement(tokens, i, depth + 1)
            children.append(child)
        if i == len(tokens):
            raise RTLExtractionError("unclosed begin/end block")
        i += 1
        if i < len(tokens) and tokens[i].text == ":":
            i += 2
        return Statement("block", tokens[start:i], children=children), i
    if word == "if":
        condition, i = bracket(tokens, i)
        yes, i = statement(tokens, i, depth + 1)
        children = [yes]
        if i < len(tokens) and tokens[i].text == "else":
            no, i = statement(tokens, i + 1, depth + 1)
            children.append(no)
        return Statement("if", tokens[start:i], condition, children), i
    if word in ("case", "casex", "casez"):
        selector, i = bracket(tokens, i)
        children = []
        while i < len(tokens) and tokens[i].text != "endcase":
            j, nesting = i, 0
            while j < len(tokens):
                w = tokens[j].text
                if w in ("(", "[", "{"):
                    nesting += 1
                elif w in (")", "]", "}"):
                    nesting -= 1
                if w == ":" and nesting == 0:
                    break
                j += 1
            if j == len(tokens):
                raise RTLExtractionError("case item has no colon")
            child, end = statement(tokens, j + 1, depth + 1)
            children.append(Statement("case_item", tokens[i:end], tokens[i:j], [child]))
            i = end
        if i == len(tokens):
            raise RTLExtractionError("unclosed case statement")
        return Statement("case", tokens[start:i + 1], selector, children), i + 1
    if word in ("for", "while", "repeat"):
        condition, i = bracket(tokens, i)
        child, i = statement(tokens, i, depth + 1)
        return Statement("loop", tokens[start:i], condition, [child]), i
    if word in ("unique", "unique0", "priority"):
        return statement(tokens, i, depth + 1)
    content, i = until_semicolon(tokens, start)
    return Statement("simple", content), i


def assignment(tokens: list[Token]) -> tuple[list[Token], list[Token]] | None:
    depth = 0
    for i, token in enumerate(tokens):
        word = token.text
        if word in ("(", "[", "{"):
            depth += 1
        elif word in (")", "]", "}"):
            depth -= 1
        elif depth == 0 and word in ("=", "<="):
            lhs, rhs = tokens[:i], tokens[i + 1:]
            # Delay values are scheduling expressions, not data inputs.
            if rhs and rhs[0].text == "#":
                if len(rhs) > 1 and rhs[1].text == "(":
                    _, end = bracket(rhs, 1)
                    rhs = rhs[end:]
                else:
                    rhs = rhs[2:]
            return (lhs, rhs) if lhs and rhs else None
    return None


def lhs_names(tokens: list[Token]) -> tuple[list[str], list[str]]:
    """Targets of a concatenation/selection; selection indices are reads, never writes."""
    targets, indices = [], []
    i = 0
    while i < len(tokens):
        word = tokens[i].text
        if word == "[":
            part, i = bracket(tokens, i, "[", "]")
            indices.extend(identifiers(part))
        elif re.fullmatch(IDENT, word) and word not in RESERVED:
            targets.append(word)
            i += 1
        elif word in ("{", "}", ","):
            i += 1
        else:
            raise RTLExtractionError(f"unsupported assignment target: {spelling(tokens)}")
    return sorted(set(targets)), sorted(set(indices))


def parameter_items(tokens: list[Token]) -> list[dict]:
    result = []
    local = False
    sized_type = False
    integer_type = False
    for group in split_at(tokens, ","):
        eq = next((i for i, t in enumerate(group) if t.text == "="), -1)
        if eq < 1 or re.fullmatch(IDENT, group[eq - 1].text) is None:
            raise RTLExtractionError(f"unsupported parameter: {spelling(group)}")
        if group and group[0].text in ("parameter", "localparam"):
            local = group[0].text == "localparam"
            sized_type = integer_type = False
        prefix = [t.text for t in group[:eq - 1]]
        if "int" in prefix or "integer" in prefix:
            integer_type = True
        if any(t in prefix for t in ("[", "logic", "bit", "unsigned", "type", "string", "real")):
            sized_type = True
        sized = sized_type or (not integer_type and any("'" in t.text for t in group[eq + 1:]))
        result.append(dict(name=group[eq - 1].text, tokens=group[eq + 1:], source=group, local=local,
                           sized=sized, typed_sized=sized_type, integer_type=integer_type))
    return result


def instance_items(tokens: list[Token]) -> list[dict] | None:
    if len(tokens) < 3 or re.fullmatch(IDENT, tokens[0].text) is None or tokens[0].text in RESERVED:
        return None
    module_type, i = tokens[0].text, 1
    parameters = []
    if tokens[i].text == "#":
        parameters, i = bracket(tokens, i + 1)
    instances = []
    while i < len(tokens):
        if re.fullmatch(IDENT, tokens[i].text) is None or tokens[i].text in RESERVED:
            return None
        name, i = tokens[i].text, i + 1
        if i >= len(tokens) or tokens[i].text != "(":
            return None
        connections, i = bracket(tokens, i)
        instances.append(dict(module_type=module_type, name=name, parameters=parameters,
                              connections=connections, source=tokens))
        if i == len(tokens):
            break
        if tokens[i].text != ",":
            return None
        i += 1
    return instances


def parse_module(name: str, header: list[Token], body: list[Token], source: list[Token]) -> dict:
    result = dict(name=name, ports=[], parameters=[], signals={}, processes=[], assignments=[],
                  instances=[], gaps=[], source=source)
    i = 0
    if header and header[0].text == "#":
        params, i = bracket(header, 1)
        result["parameters"] += parameter_items(params)
    port_tokens = []
    if i < len(header):
        port_tokens, end = bracket(header, i)
        if end != len(header):
            raise RTLExtractionError(f"unsupported module header: {name}")
    ansi = bool(port_tokens and port_tokens[0].text in ("input", "output", "inout"))
    if ansi:
        result["ports"], _ = _ports(port_tokens)
        header_names = [p["name"] for p in result["ports"]]
    else:
        header_names = []
        for group in split_at(port_tokens, ",") if port_tokens else []:
            if len(group) != 1 or re.fullmatch(IDENT, group[0].text) is None:
                raise RTLExtractionError(f"unsupported port expression in {name}")
            header_names.append(group[0].text)
    i = 0
    while i < len(body):
        start, word = i, body[i].text
        if word in ("function", "task", "generate", "specify"):
            ending = {"function": "endfunction", "task": "endtask", "generate": "endgenerate", "specify": "endspecify"}[word]
            end = next((j for j in range(i + 1, len(body)) if body[j].text == ending), None)
            if end is None:
                raise RTLExtractionError(f"unclosed {word} in {name}")
            result["gaps"].append((f"{word} body not analyzed/elaborated", body[i:end + 1]))
            i = end + 1
            continue
        if word in ("always", "always_ff", "always_comb", "always_latch", "initial"):
            i += 1
            events = []
            if i < len(body) and body[i].text == "@":
                i += 1
                if body[i].text == "(":
                    events, i = bracket(body, i)
                else:
                    events, i = [body[i]], i + 1
            parsed, i = statement(body, i)
            result["processes"].append(dict(kind=word, events=events, statement=parsed, source=body[start:i]))
            continue
        content, i = until_semicolon(body, start)
        if not content:
            continue
        if word in ("input", "output", "inout"):
            ports, _ = _ports(content)
            result["ports"].extend(ports)
        elif word in ("parameter", "localparam"):
            result["parameters"] += parameter_items(content)
        elif word in ("wire", "reg", "logic", "bit", "tri", "integer", "int", "genvar"):
            # Only declarations, not initialization RHS identifiers, enter the symbol table.
            clean = []
            for group in split_at(content[1:], ","):
                if clean:
                    clean.append(Token(",", content[0].path, content[0].line, content[0].quote))
                clean += split_at(group, "=")[0]
            synthetic = Token("input", content[0].path, content[0].line, content[0].quote)
            declarations, _ = _ports([synthetic] + clean)
            for d in declarations:
                result["signals"][d["name"]] = dict(tokens=content, declaration=d)
            for index, group in enumerate(split_at(content[1:], ",")):
                eq = next((j for j, t in enumerate(group) if t.text == "="), None)
                if eq is not None:
                    token = group[0]
                    lhs = Token(declarations[index]["name"], token.path, token.line, token.quote)
                    parsed = Statement("simple", [lhs] + group[eq:])
                    if word in ("wire", "tri"):
                        result["assignments"].append(parsed)
                    else:
                        result["processes"].append(dict(kind="declaration_init", events=[], statement=parsed,
                                                        source=content))
        elif word == "assign":
            for group in split_at(content[1:], ","):
                result["assignments"].append(Statement("simple", group))
        elif word in ("timeunit", "timeprecision"):
            continue
        else:
            instances = instance_items(content)
            if instances:
                result["instances"] += instances
            else:
                result["gaps"].append(("unsupported module item", content))
    ports = {p["name"]: p for p in result["ports"]}
    if len(ports) != len(result["ports"]) or set(header_names) != set(ports):
        raise RTLExtractionError(f"port declarations do not match header in {name}")
    result["ports"] = [ports[n] for n in header_names]
    return result


def parse_design(tokens: list[Token]) -> dict[str, dict]:
    modules = {}
    i = 0
    while i < len(tokens):
        if tokens[i].text != "module":
            i += 1
            continue
        start, i = i, i + 1
        if tokens[i].text in ("automatic", "static"):
            i += 1
        name, i = tokens[i].text, i + 1
        header, body_start = until_semicolon(tokens, i)
        end = next((j for j in range(body_start, len(tokens)) if tokens[j].text == "endmodule"), None)
        if end is None or name in modules:
            raise RTLExtractionError(f"duplicate or unterminated module: {name}")
        modules[name] = parse_module(name, header, tokens[body_start:end], tokens[start:body_start])
        i = end + 1
    return modules
