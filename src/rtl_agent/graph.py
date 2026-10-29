"""Source-backed hierarchy, dependency and clock/reset graph for the RTL coding flow."""
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from .constants import evaluate
from .design import (Statement, assignment, has_local_declarations, identifiers, lhs_names, parse_design)
from .fsutil import atomic_write_text
from .source import IDENT, Preprocessor, RTLExtractionError, Token, bracket, spelling, split_at

WEIGHTS = {"CONTAINS": .25, "DERIVED_FROM": .7, "INSTANCE_OF": .3, "READS": .8,
           "WRITES": .85, "DATA_DEPENDS_ON": .95, "CONTROL_DEPENDS_ON": .85,
           "CONTROLLED_BY": .8, "PORT_DEPENDS_ON": .98, "ALIASES": .98,
           "CLOCKED_BY": .7, "RESET_BY": .7, "SENSITIVE_TO": .6,
           "MEMBER_OF": .25, "FEATURE_MEMBER": .8, "PARAMETERIZED_BY": .5}
FLOW_EDGES = {"DATA_DEPENDS_ON", "CONTROL_DEPENDS_ON", "PORT_DEPENDS_ON"}


@dataclass
class BuildConfig:
    max_nodes: int = 20_000
    max_edges: int = 100_000
    max_instances: int = 256
    max_depth: int = 16
    excerpt_lines: int = 40

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in vars(self).values()):
            raise RTLExtractionError("graph build budgets must be positive integers")
        if (self.max_depth > 64 or self.max_instances > 4096 or self.max_nodes > 100_000
                or self.max_edges > 500_000 or self.excerpt_lines > 200):
            raise RTLExtractionError("graph build budgets exceed supported limits")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class GraphBuilder:
    def __init__(self, modules: dict, sources: dict, cfg: BuildConfig):
        self.modules, self.sources, self.cfg = modules, sources, cfg
        self.G = nx.MultiDiGraph(kind="rtl_static_graph", top="", diagnostics=[])
        self.contexts: dict[str, dict] = {}
        self.instances = 0
        self.aliases = nx.Graph()
        self.source_text: dict[str, str] = {}
        for path, source in sorted(sources.items()):
            raw = Path(path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise RTLExtractionError(f"source changed during graph build: {path}")
            self.source_text[path] = raw.decode("utf-8")

    def node(self, nid: str, **data) -> str:
        if nid not in self.G and len(self.G) >= self.cfg.max_nodes:
            raise RTLExtractionError("RTL graph node budget exhausted")
        if nid not in self.G and data.get("type") == "instance":
            self.instances += 1
            if self.instances > self.cfg.max_instances:
                raise RTLExtractionError("RTL hierarchy instance budget exhausted")
        self.G.add_node(nid, **data)
        return nid

    def edge(self, u: str, v: str, kind: str, evidence: list[str], *, status="DOCUMENTED", **data):
        if not self.G.has_edge(u, v, key=kind) and self.G.number_of_edges() >= self.cfg.max_edges:
            raise RTLExtractionError("RTL graph edge budget exhausted")
        previous = self.G.get_edge_data(u, v, key=kind) or {}
        evidence = sorted(set(evidence) | set(previous.get("evidence", [])))
        self.G.add_edge(u, v, key=kind, type=kind, weight=WEIGHTS[kind], evidence=evidence,
                        status=status, **data)

    def evidence(self, tokens: list[Token]) -> list[str]:
        spans: dict[str, set[int]] = {}
        for t in tokens:
            spans.setdefault(t.path, set()).add(t.line)
        ids = []
        for path, numbers in sorted(spans.items()):
            text = self.source_text[path]
            lines = text.splitlines(keepends=True)
            offsets = [0]
            for line in lines:
                offsets.append(offsets[-1] + len(line))
            for first in range(min(numbers), max(numbers) + 1, self.cfg.excerpt_lines):
                last = min(first + self.cfg.excerpt_lines - 1, max(numbers))
                start, end = offsets[first - 1], offsets[last]
                quote = text[start:end]
                nid = "SRC:" + _hash(path + self.sources[path]["sha256"] + f":{start}:{end}")
                self.node(nid, layer=1, type="excerpt", label=f"{Path(path).name}:{first}-{last}",
                          path=path, line_start=first, line_end=last, char_start=start, char_end=end,
                          text=quote, text_sha256=hashlib.sha256(quote.encode()).hexdigest(),
                          file_sha256=self.sources[path]["sha256"])
                ids.append(nid)
        return ids

    def entity(self, nid: str, kind: str, label: str, scope: str, tokens: list[Token], **attrs) -> str:
        evidence = self.evidence(tokens)
        self.node(nid, layer=2, type=kind, label=label, scope=scope, evidence=evidence, **attrs)
        for cid in evidence:
            self.edge(nid, cid, "DERIVED_FROM", [cid])
        return nid

    def gap(self, reason: str, scope: str, tokens: list[Token]):
        self.G.graph["diagnostics"].append(dict(reason=reason, scope=scope, evidence=self.evidence(tokens)))

    def signal(self, ctx: dict, name: str, tokens: list[Token]) -> str:
        if name not in ctx["signals"]:
            nid = "SIG:" + ctx["scope"] + "." + name
            self.entity(nid, "signal", ctx["scope"] + "." + name, ctx["scope"], tokens,
                        name=name, direction="internal", implicit=True)
            self.edge(ctx["instance"], nid, "CONTAINS", self.G.nodes[nid]["evidence"])
            ctx["signals"][name] = nid
            self.gap(f"implicit signal declaration: {name}", ctx["scope"], tokens)
        return ctx["signals"][name]

    def refs(self, ctx: dict, tokens: list[Token]) -> list[str]:
        if any(t.text in (".", "::") for t in tokens):
            self.gap("hierarchical/package expression not resolved: " + spelling(tokens), ctx["scope"], tokens)
            return []
        names = identifiers(tokens)
        unknown = set(names) - set(ctx["signals"]) - set(ctx["parameters"])
        if unknown:
            self.gap("unresolved references/functions: " + ", ".join(sorted(unknown)), ctx["scope"], tokens)
        return [ctx["signals"][n] for n in names if n in ctx["signals"]]

    def expand(self, module_type: str, scope: str, parameter_values: dict | None = None,
               stack: tuple[str, ...] = ()) -> dict:
        if len(self.contexts) >= self.cfg.max_instances or len(stack) >= self.cfg.max_depth:
            raise RTLExtractionError("RTL hierarchy instance/depth budget exhausted")
        if module_type in stack:
            raise RTLExtractionError(f"recursive module instantiation: {' -> '.join(stack + (module_type,))}")
        definition = self.modules[module_type]
        if scope in self.contexts:
            raise RTLExtractionError(f"duplicate instance path: {scope}")
        module = "MOD:" + module_type
        if module not in self.G:
            self.entity(module, "module", module_type, "", definition["source"])
        instance = "INST:" + scope
        self.entity(instance, "instance", scope, scope, definition["source"], module_type=module_type)
        evidence = self.G.nodes[instance]["evidence"]
        self.edge(instance, module, "INSTANCE_OF", evidence)
        ctx = dict(scope=scope, instance=instance, signals={}, parameters={}, definition=definition,
                   sized_parameters={p["name"] for p in definition["parameters"] if p["sized"]})
        self.contexts[scope] = ctx
        for p in definition["parameters"]:
            ctx["parameters"][p["name"]] = None
        for _ in range(len(definition["parameters"]) + 1):
            changed = False
            for p in definition["parameters"]:
                if ctx["parameters"][p["name"]] is not None:
                    continue
                if p["typed_sized"]:
                    continue
                references = set(identifiers(p["tokens"]))
                if references & ctx["sized_parameters"]:
                    ctx["sized_parameters"].add(p["name"])
                    if len(p["tokens"]) > 1 and p["name"] not in (parameter_values or {}):
                        continue
                try:
                    value = ((parameter_values or {})[p["name"]] if p["name"] in (parameter_values or {})
                             else evaluate(p["tokens"], {k: v for k, v in ctx["parameters"].items() if v is not None}))
                except RTLExtractionError:
                    continue
                ctx["parameters"][p["name"]], changed = value, True
            if not changed:
                break
        for p in definition["parameters"]:
            nid = "PAR:" + scope + "." + p["name"]
            self.entity(nid, "parameter", scope + "." + p["name"], scope, p["source"],
                        expression=spelling(p["tokens"]), value=ctx["parameters"][p["name"]])
            self.edge(instance, nid, "PARAMETERIZED_BY", self.G.nodes[nid]["evidence"])
            if ctx["parameters"][p["name"]] is None:
                self.gap(f"parameter left symbolic (unresolved/sizing semantics): {p['name']}", scope, p["source"])
        for p in definition["ports"]:
            token = Token(p["name"], p["source"]["path"], p["source"]["line"], p["source"]["quote"])
            nid = "SIG:" + scope + "." + p["name"]
            dimensions = p["packed_tokens"]
            self.entity(nid, "signal", scope + "." + p["name"], scope, [token], name=p["name"],
                        direction=p["direction"], declared_range="".join("[" + spelling(d) + "]" for d in dimensions))
            ctx["signals"][p["name"]] = nid
            self.edge(instance, nid, "CONTAINS", self.G.nodes[nid]["evidence"])
        for name, declaration in sorted(definition["signals"].items()):
            if name not in ctx["signals"]:
                nid = "SIG:" + scope + "." + name
                self.entity(nid, "signal", scope + "." + name, scope, declaration["tokens"],
                            name=name, direction="internal")
                ctx["signals"][name] = nid
                self.edge(instance, nid, "CONTAINS", self.G.nodes[nid]["evidence"])
        for reason, tokens in definition["gaps"]:
            self.gap(reason, scope, tokens)
        # Resolve implicit assignment targets before analyzing any RHS; source order is not net declaration order.
        for root in [p["statement"] for p in definition["processes"]] + definition["assignments"]:
            if has_local_declarations(root):
                continue
            pending = [root]
            while pending:
                statement = pending.pop()
                pending += statement.children
                pair = assignment(statement.tokens) if statement.kind == "simple" else None
                if pair:
                    try:
                        names, _ = lhs_names(pair[0])
                    except RTLExtractionError:
                        continue
                    for name in names:
                        self.signal(ctx, name, pair[0])
        for ordinal, process in enumerate(definition["processes"]):
            self.process(ctx, process, ordinal)
        for ordinal, statement in enumerate(definition["assignments"]):
            pid = "PROC:" + scope + f":assign:{ordinal}"
            self.entity(pid, "process", f"{scope}: continuous assignment {ordinal}", scope, statement.tokens,
                        process_kind="assign")
            self.edge(instance, pid, "CONTAINS", self.G.nodes[pid]["evidence"])
            self.walk(ctx, pid, statement, [])
        for spec in definition["instances"]:
            child_scope = scope + "." + spec["name"]
            if spec["module_type"] not in self.modules:
                child = self.entity("INST:" + child_scope, "instance", child_scope, child_scope, spec["source"],
                                    module_type=spec["module_type"], unresolved=True)
                self.edge(instance, child, "CONTAINS", self.evidence(spec["source"]))
                self.gap(f"missing module definition: {spec['module_type']}", child_scope, spec["source"])
                continue
            child_definition = self.modules[spec["module_type"]]
            overrides = self.parameter_bindings(ctx, spec["parameters"], child_definition, spec["source"])
            child_ctx = self.expand(spec["module_type"], child_scope, parameter_values=overrides,
                                    stack=stack + (module_type,))
            self.edge(instance, child_ctx["instance"], "CONTAINS", self.evidence(spec["source"]))
            self.connect(ctx, child_ctx, spec)
        return ctx

    def parameter_bindings(self, ctx: dict, tokens: list[Token], child: dict, source: list[Token]) -> dict:
        result = {}
        if not tokens:
            return result
        names = [p["name"] for p in child["parameters"] if not p["local"]]
        for i, part in enumerate(split_at(tokens, ",")):
            name, expression = (names[i] if i < len(names) else "", part)
            if part and part[0].text == "." and len(part) > 2:
                name = part[1].text
                expression, end = bracket(part, 2)
                if end != len(part):
                    raise RTLExtractionError("unsupported parameter binding")
            if name not in names or name in result:
                raise RTLExtractionError(f"unknown/duplicate parameter binding: {name}")
            try:
                if set(identifiers(expression)) & ctx["sized_parameters"]:
                    raise RTLExtractionError("parameter binding needs sized constant semantics")
                result[name] = evaluate(expression, {k: v for k, v in ctx["parameters"].items() if v is not None})
            except RTLExtractionError:
                self.gap(f"unresolved instance parameter {name}: {spelling(expression)}", ctx["scope"], source)
                # Never silently substitute the child's default for an unresolved override.
                result[name] = None
        return result

    def connect(self, parent: dict, child: dict, spec: dict):
        ports = child["definition"]["ports"]
        names = [p["name"] for p in ports]
        parts = split_at(spec["connections"], ",") if spec["connections"] else []
        styles = {"named" if part and part[0].text == "." else "positional" for part in parts}
        if len(styles) > 1:
            raise RTLExtractionError(f"mixed named/positional connections on {child['scope']}")
        bound, wildcard = {}, False
        for index, part in enumerate(parts):
            if [t.text for t in part] == [".", "*"]:
                wildcard = True
                continue
            if part and part[0].text == ".":
                name = part[1].text
                if len(part) == 2:
                    expression = [part[1]]
                else:
                    expression, end = bracket(part, 2)
                    if end != len(part):
                        raise RTLExtractionError("unsupported named port connection")
            else:
                if index >= len(names):
                    raise RTLExtractionError(f"too many positional ports on {child['scope']}")
                name, expression = names[index], part
            if name not in names or name in bound:
                raise RTLExtractionError(f"unknown/duplicate port {name} on {child['scope']}")
            bound[name] = expression
        if wildcard:
            for name in names:
                if name not in bound and name in parent["signals"]:
                    token = spec["source"][0]
                    bound[name] = [Token(name, token.path, token.line, token.quote)]
        evidence = self.evidence(spec["source"])
        for port in ports:
            name, direction = port["name"], port["direction"]
            expression = bound.get(name)
            if expression is None or not expression:
                self.gap(f"unconnected port: {name}", child["scope"], spec["source"])
                continue
            formal = child["signals"][name]
            self.G.nodes[formal]["binding_expression"] = spelling(expression)
            if (len(expression) == 1 and expression[0].text not in parent["parameters"]
                    and re.fullmatch(IDENT, expression[0].text)):
                self.signal(parent, expression[0].text, expression)
            if direction in ("output", "inout"):
                targets, indices = lhs_names(expression)
                actuals = [self.signal(parent, n, expression) for n in targets]
                if indices:
                    self.gap("indexed output connection modeled at whole-signal level", child["scope"], expression)
            else:
                actuals = self.refs(parent, expression)
            for actual in actuals:
                src, dst = (formal, actual) if direction == "input" else (actual, formal)
                if direction == "inout":
                    self.gap("bidirectional connection has no resolved drive policy", child["scope"], expression)
                else:
                    self.edge(src, dst, "PORT_DEPENDS_ON", evidence, expression=spelling(expression),
                              direction=direction, status="INFERRED")
                if len(expression) == 1 and len(actuals) == 1:
                    self.edge(formal, actual, "ALIASES", evidence)
                    self.aliases.add_edge(formal, actual)
            if not actuals and not identifiers(expression):
                self.G.nodes[formal]["constant_binding"] = spelling(expression)

    def process(self, ctx: dict, process: dict, ordinal: int):
        pid = "PROC:" + ctx["scope"] + f":{ordinal}"
        self.entity(pid, "process", f"{ctx['scope']}: {process['kind']} {ordinal}", ctx["scope"], process["source"],
                    process_kind=process["kind"], sensitivity=spelling(process["events"]))
        evidence = self.G.nodes[pid]["evidence"]
        self.edge(ctx["instance"], pid, "CONTAINS", evidence)
        if has_local_declarations(process["statement"]):
            self.gap("process-local declarations/shadowing not resolved; body omitted", ctx["scope"], process["source"])
            return
        events = []
        for i, t in enumerate(process["events"]):
            if t.text in ("posedge", "negedge"):
                suffix = process["events"][i + 1:]
                if suffix and suffix[0].text in ctx["signals"] and (len(suffix) == 1 or suffix[1].text in ("or", ",")):
                    events.append((suffix[0].text, t.text))
                else:
                    self.gap("complex event expression not resolved", ctx["scope"], process["events"])
        reset = self.reset_candidate(ctx, process["statement"])
        reset_name = reset[0] if reset else None
        clocks = [(n, edge) for n, edge in events if n != reset_name]
        if len(clocks) == 1:
            name, edge = clocks[0]
            self.edge(pid, ctx["signals"][name], "CLOCKED_BY", evidence, edge=edge, status="INFERRED")
        elif clocks:
            self.gap("multiple event signals; clock role is ambiguous", ctx["scope"], process["events"])
        for name, edge in events:
            self.edge(pid, ctx["signals"][name], "SENSITIVE_TO", evidence, edge=edge)
        if reset and events:
            name, active, condition = reset
            event_edges = [e for n, e in events if n == name]
            mode = "asynchronous" if event_edges else "synchronous"
            if event_edges and event_edges != ["posedge" if active else "negedge"]:
                self.gap("reset condition and sensitivity polarity disagree", ctx["scope"], condition)
                mode = "ambiguous"
            self.edge(pid, ctx["signals"][name], "RESET_BY", self.evidence(condition),
                      mode=mode, active="high" if active else "low", status="INFERRED",
                      basis="leading conditional branch assigns constants; reset role needs review")
        self.walk(ctx, pid, process["statement"], [])
        written = [v for _, v, k in list(self.G.out_edges(pid, keys=True)) if k == "WRITES"]
        domains = [(v, k, dict(d)) for _, v, k, d in self.G.out_edges(pid, keys=True, data=True)
                   if k in ("CLOCKED_BY", "RESET_BY")]
        for target in written:
            for signal, kind, data in domains:
                self.edge(target, signal, kind, data["evidence"],
                          **{k: v for k, v in data.items() if k not in ("type", "weight", "evidence")})

    def reset_candidate(self, ctx: dict, node: Statement):
        while node.kind == "block" and node.children:
            node = node.children[0]
        if node.kind != "if":
            return None
        condition = spelling(node.condition).replace(" ", "")
        while condition.startswith("(") and condition.endswith(")"):
            condition = condition[1:-1]
        candidates = []
        for name in identifiers(node.condition):
            if name not in ctx["signals"]:
                continue
            if condition == name:
                candidates.append((name, True))
            elif condition in ("!" + name, "~" + name):
                candidates.append((name, False))
            else:
                match = re.fullmatch(re.escape(name) + r"==((?:1'[bBdD])?[01])", condition)
                if match:
                    candidates.append((name, match[1][-1] == "1"))
        if len(candidates) != 1:
            return None
        stack, count = [node.children[0]], 0
        while stack:
            child = stack.pop()
            stack.extend(child.children)
            pair = assignment(child.tokens) if child.kind == "simple" else None
            if pair:
                if self.refs(ctx, pair[1]) or set(identifiers(pair[1])) - set(ctx["parameters"]):
                    return None
                count += 1
        return (*candidates[0], node.condition) if count else None

    def walk(self, ctx: dict, pid: str, node: Statement, guards: list[str]):
        if node.kind in ("if", "case", "case_item", "loop"):
            cid = "COND:" + _hash(pid + spelling(node.condition) + str(node.tokens[0].line))
            self.entity(cid, "condition", f"{ctx['scope']}: {node.kind} {spelling(node.condition)}", ctx["scope"],
                        node.condition or node.tokens[:1], expression=spelling(node.condition), navigation_only=True)
            for signal in self.refs(ctx, node.condition):
                self.edge(cid, signal, "READS", self.G.nodes[cid]["evidence"])
            if node.kind == "loop":
                self.gap("procedural loop modeled symbolically, not unrolled", ctx["scope"], node.tokens)
            guards = guards + [cid]
        if node.kind != "simple":
            for child in node.children:
                self.walk(ctx, pid, child, guards)
            return
        if not node.tokens:
            return
        pair = assignment(node.tokens)
        if pair is None:
            if not node.tokens[0].text.startswith("$"):
                self.gap("statement has no analyzed assignment: " + spelling(node.tokens), ctx["scope"], node.tokens)
            return
        lhs, rhs = pair
        try:
            names, indices = lhs_names(lhs)
        except RTLExtractionError as exc:
            self.gap(str(exc), ctx["scope"], node.tokens)
            return
        evidence = self.evidence(node.tokens)
        reads = self.refs(ctx, rhs)
        reads += [ctx["signals"][n] for n in indices if n in ctx["signals"]]
        for name in names:
            target = self.signal(ctx, name, lhs)
            self.edge(pid, target, "WRITES", evidence)
            for source in reads:
                self.edge(pid, source, "READS", evidence)
                self.edge(target, source, "DATA_DEPENDS_ON", evidence, status="INFERRED",
                          expression=spelling(rhs), granularity="whole_signal")
            for condition in guards:
                self.edge(target, condition, "CONTROLLED_BY", evidence, status="INFERRED")
                for _, source, key in list(self.G.out_edges(condition, keys=True)):
                    if key == "READS":
                        self.edge(target, source, "CONTROL_DEPENDS_ON", evidence + self.G.nodes[condition]["evidence"],
                                  status="INFERRED", condition=self.G.nodes[condition]["expression"])
        if len(names) == 1 and len(lhs) == 1 and len(rhs) == 1 and rhs[0].text in ctx["signals"]:
            target, source = ctx["signals"][names[0]], ctx["signals"][rhs[0].text]
            if self.G.nodes[pid].get("process_kind") == "assign":
                self.aliases.add_edge(target, source)
                self.edge(target, source, "ALIASES", evidence)

    def finish(self, features: dict | None):
        # Clock identity propagates through exact scalar aliases/port connections only.
        components = {}
        for component in nx.connected_components(self.aliases):
            canonical = min(component, key=lambda n: (self.G.nodes[n]["label"].count("."), n))
            for signal in component:
                components[signal] = canonical
        domains = {}
        for u, v, kind, d in self.G.edges(keys=True, data=True):
            if kind not in ("CLOCKED_BY", "RESET_BY"):
                continue
            root = components.get(v, v)
            d["root_signal"] = root
            domains.setdefault(root, {"signal": root, "clocked": [], "reset": []})[
                "clocked" if kind == "CLOCKED_BY" else "reset"].append(u)
        self.G.graph["domains"] = [dict(d, clocked=sorted(set(d["clocked"])), reset=sorted(set(d["reset"])))
                                   for _, d in sorted(domains.items())]
        registers = {}
        for u, v, kind, data in self.G.edges(keys=True, data=True):
            if kind == "CLOCKED_BY" and self.G.nodes[u]["type"] == "signal":
                registers.setdefault(u, set()).add(data["root_signal"])
        crossings = []
        for target in sorted(registers):
            frontier, seen = [(target, [target])], {target}
            while frontier and len(seen) < 256 and len(crossings) < 100:
                node, path = frontier.pop(0)
                if len(path) > 8:
                    continue
                for _, dependency, kind in sorted(self.G.out_edges(node, keys=True)):
                    if kind not in FLOW_EDGES or dependency in seen:
                        continue
                    seen.add(dependency)
                    route = path + [dependency]
                    if dependency in registers:
                        if registers[target].isdisjoint(registers[dependency]):
                            crossings.append(dict(source=dependency, target=target, path=route,
                                                  source_clocks=sorted(registers[dependency]),
                                                  target_clocks=sorted(registers[target]), status="NEEDS_REVIEW"))
                    else:
                        frontier.append((dependency, route))
        self.G.graph["domain_crossings"] = crossings
        labels = {d["label"]: n for n, d in self.G.nodes(data=True) if d["type"] in ("signal", "instance")}
        for name, spec in sorted((features or {}).items()):
            if not isinstance(spec, dict) or not isinstance(spec.get("targets"), list) or not spec["targets"]:
                raise RTLExtractionError(f"feature {name} needs an explicit nonempty targets list")
            targets = spec["targets"]
            if any(t not in labels for t in targets):
                raise RTLExtractionError(f"feature {name} has unknown targets")
            nid = "FEATURE:" + name
            self.node(nid, layer=2, type="feature", label=name, scope="", evidence=[],
                      description=str(spec.get("description", "")), status="INFERRED", navigation_only=True)
            for target in sorted(set(targets)):
                self.edge(nid, labels[target], "FEATURE_MEMBER", self.G.nodes[labels[target]]["evidence"],
                          status="INFERRED")
        semantic = nx.Graph()
        semantic.add_nodes_from(sorted(n for n, d in self.G.nodes(data=True) if d["layer"] == 2))
        for u, v, kind, d in sorted(self.G.edges(keys=True, data=True)):
            if u in semantic and v in semantic and kind not in ("CONTAINS", "INSTANCE_OF", "PARAMETERIZED_BY"):
                semantic.add_edge(u, v, weight=d["weight"])
        communities = sorted((sorted(c) for c in nx.community.asyn_lpa_communities(semantic, weight="weight", seed=0)),
                             key=lambda c: c[0])
        for members in communities:
            if len(members) < 2:
                continue
            nid = "COMM:" + _hash("|".join(members))
            summary = "; ".join(self.G.nodes[n]["label"] for n in members[:16])
            self.node(nid, layer=3, type="community", label="Connected RTL group", summary=summary,
                      members=members, navigation_only=True, evidence=[])
            for n in members:
                self.edge(n, nid, "MEMBER_OF", [])
        diagnostics = {json.dumps(d, sort_keys=True): d for d in self.G.graph["diagnostics"]}
        self.G.graph["diagnostics"] = [diagnostics[k] for k in sorted(diagnostics)]
        self.G.graph["analysis_status"] = "PARTIAL" if diagnostics else "PASS"
        self.G.graph["statistics"] = dict(nodes=len(self.G), edges=self.G.number_of_edges(), instances=self.instances,
                                          resolved_instances=len(self.contexts),
                                          kinds=dict(sorted(Counter(d["type"] for _, d in self.G.nodes(data=True)).items())))


def build_graph(files: list[Path], top: str, *, include_dirs: list[Path] | None = None,
                defines: dict[str, str] | None = None, overrides: dict[str, str] | None = None,
                features: dict | None = None, cfg: BuildConfig | None = None) -> nx.MultiDiGraph:
    if not files or len(files) > 256 or re.fullmatch(IDENT, top) is None:
        raise RTLExtractionError("provide a simple top name and 1..256 explicit source files")
    cfg = cfg or BuildConfig()
    pp = Preprocessor(include_dirs or [], defines or {})
    tokens = []
    for path in files:
        tokens += pp.read(path)
    modules = parse_design(tokens)
    if top not in modules:
        raise RTLExtractionError(f"top module not found: {top}")
    parameter_values = {}
    allowed = {p["name"] for p in modules[top]["parameters"] if not p["local"]}
    for name, value in (overrides or {}).items():
        if name not in allowed:
            raise RTLExtractionError(f"unknown top parameter override: {name}")
        parameter = next(p for p in modules[top]["parameters"] if p["name"] == name)
        if "'" in value and not parameter["integer_type"]:
            raise RTLExtractionError("sized top overrides require integer-typed parameters or a compiler frontend")
        from .source import TOKEN
        parameter_values[name] = evaluate([Token(m[0], "<override>", 1, value) for m in TOKEN.finditer(value)], {})
    builder = GraphBuilder(modules, pp.files, cfg)
    builder.G.graph.update(top=top, sources=[pp.files[p] for p in sorted(pp.files)],
                           configuration=dict(files=[str(p.resolve()) for p in files], defines=defines or {},
                                              overrides=overrides or {}, include_dirs=[str(p.resolve()) for p in include_dirs or []]))
    builder.expand(top, top, parameter_values=parameter_values)
    builder.finish(features)
    return builder.G


def graph_data(G: nx.MultiDiGraph) -> dict:
    return dict(metadata=G.graph,
                nodes=[dict(id=n, **d) for n, d in sorted(G.nodes(data=True))],
                edges=[dict(source=u, target=v, **d) for u, v, k, d in sorted(G.edges(keys=True, data=True))])


def save_graph(G: nx.MultiDiGraph, path: Path):
    if path.is_symlink() or path.resolve() in {Path(s["path"]).resolve() for s in G.graph["sources"]}:
        raise RTLExtractionError("refusing to overwrite a source or linked graph artifact")
    atomic_write_text(path, json.dumps(graph_data(G), indent=2) + "\n")


def load_graph(path: Path) -> nx.MultiDiGraph:
    if path.stat().st_size > 64 * 1024 * 1024:
        raise RTLExtractionError("saved RTL graph exceeds the 64 MiB input budget")
    data = json.loads(path.read_text())
    if data.get("metadata", {}).get("kind") != "rtl_static_graph":
        raise RTLExtractionError("expected an RTL static graph artifact")
    if len(data["nodes"]) > 100_000 or len(data["edges"]) > 500_000:
        raise RTLExtractionError("saved RTL graph exceeds supported budgets")
    G = nx.MultiDiGraph(**data["metadata"])
    for n in data["nodes"]:
        n = dict(n)
        G.add_node(n.pop("id"), **n)
    for edge in data["edges"]:
        e = dict(edge)
        u, v = e.pop("source"), e.pop("target")
        if u not in G or v not in G or e["type"] not in WEIGHTS:
            raise RTLExtractionError("invalid RTL graph edge endpoint/type")
        G.add_edge(u, v, key=e["type"], **e)
    return G
