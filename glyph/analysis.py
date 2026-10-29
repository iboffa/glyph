"""Conservative typed region IR and allocation/effect summaries.

Regions retain source order (including short circuit and loop boundaries); they
are not a speculative, flattened list of instructions. Unknown calls and recursive
SCCs are top. This analysis deliberately does not import concurrency.PURE.
"""
from dataclasses import dataclass, field, asdict
from collections import Counter
from .syntax import Expr, Function, Record, Diagnostic

SCALAR = {'i64', 'f64', 'bool'}
# Audited runtime operations: none allocate or retain an argument. May trap.
READ = {'len', 'sum', 'count', 'i64', 'f64', 'byte_at'}
NOHEAP = READ | {'clock', 'argi', 'argc', 'free', 'move'}
ALLOC = {'range', 'fill', 'clone', 'push', 'concat', 'join', 'chr', 'str_i64',
         'str_f64', 'list', 'map', 'set', 'par_map', 'spawn', 'channel',
         'arena_fill', 'owned_fill', 'managed'}

@dataclass
class Region:
    op: str
    typ: str
    location: tuple
    operands: list = field(default_factory=list)
    body: list = field(default_factory=list)
    other: list = field(default_factory=list)
    origin: object = field(default=None, repr=False)

def lower(node):
    t = node.token
    operands = list(getattr(node, 'args', []))
    body = list(getattr(node, 'body', []))
    op = node.kind
    if node.kind == 'reduce':
        operands, body = operands[1:], operands[:1]
    elif node.kind == 'lambda':
        operands, body = [], operands
    elif node.kind == 'binary' and node.value in {'and', 'or'}:
        op = 'short_circuit:' + node.value
        operands, body = operands[:1], operands[1:]
    return Region(op, getattr(node, 'typ', ''), (t.path, t.line, t.col),
                  [lower(a) for a in operands], [lower(a) for a in body],
                  [lower(a) for a in getattr(node, 'other', [])], node)

def region_nodes(region):
    yield region.origin
    for child in region.operands + region.body + region.other:
        yield from region_nodes(child)

def walk(node):
    yield node
    for attr in ('args', 'body', 'other'):
        for child in getattr(node, attr, []):
            yield from walk(child)

@dataclass
class Summary:
    heap: bool = False
    mutation: bool = False
    escape: bool = False
    alias: bool = False
    effects: bool = False
    unknown: bool = False
    reasons: list = field(default_factory=list)

    def merge(self, other):
        for k in ('heap', 'mutation', 'escape', 'alias', 'effects', 'unknown'):
            setattr(self, k, getattr(self, k) or getattr(other, k))

class Analysis:
    def __init__(self, declarations, enabled=True, features=None):
        self.enabled = enabled
        self.features = set(features) if features is not None else {'stack', 'reuse', 'fusion', 'bounds', 'overflow'}
        self.functions = [f for f in declarations if isinstance(f, Function)]
        self.records = {r.name: r for r in declarations if isinstance(r, Record)}
        self.functions += [m for r in self.records.values() for m in r.methods]
        self.required = any(getattr(f, "noalloc", False) for f in self.functions)
        self.reuse, self.fused, self.elided = {}, set(), set()
        self.names = {f.name: f for f in self.functions if not f.owner}
        self.summaries, self.stack, self.direct, self.unchecked = {}, {}, {}, set()
        self.reports, self.ir = [], {}
        for f in self.functions:
            self.ir[id(f)] = [lower(s) for s in f.body]
            self.plan(f)
        for f in self.functions:
            self.summarize(f, set())
        for f in self.functions:
            if getattr(f, 'noalloc', False) and self.summaries[id(f)].heap:
                reason = '; '.join(self.summaries[id(f)].reasons) or 'transitive/unknown allocation'
                raise Diagnostic('G120', '@noalloc contract cannot be proved: ' + reason, f.token)

    def report(self, e, action, accepted, reason):
        self.reports.append(dict(file=e.token.path, line=e.token.line, column=e.token.col,
                                 action=action, accepted=accepted, reason=reason))

    def plan(self, f):
        # Disqualify any reference with a use outside this small, audited grammar.
        nodes = [n for s in f.body for n in walk(s)]
        bindings = Counter(n.value[0] for n in nodes if n.kind == 'var')
        bindings.update(n.value for n in nodes if n.kind in {'for', 'borrow'})
        for n in nodes:
            if n.kind == 'case':
                bindings.update(n.value[1])
        budget = 4096
        for s in nodes:
            if getattr(s, 'kind', '') != 'var':
                continue
            name, typ = s.value
            e = s.args[0]
            if bindings[name] != 1:
                self.report(e, 'stack', False, 'binding name reused in disjoint lexical scopes')
                continue
            size = None
            if typ in {'[i64]', '[f64]', '[bool]'}:
                if e.kind == 'array':
                    size = len(e.args)
                elif e.kind == 'call' and e.value in {'fill', 'range'} and e.args[0].kind == 'i64':
                    size = int(e.args[0].value)
            closure = e.kind == 'lambda' and all(t in SCALAR for _, t in e.target)
            if size is None and not closure:
                if typ.startswith('[') or e.kind == 'lambda':
                    self.report(e, 'stack', False, 'dynamic extent or reference-bearing/unsupported layout')
                continue
            valid = True
            def uses(n, parent=None, position=0):
                nonlocal valid
                if getattr(n, 'kind', '') == 'lambda' and n is not e:
                    if any(k == name for k, _ in n.target):
                        valid = False
                if getattr(n, 'kind', '') == 'name' and n.value == name:
                    ok = parent is not None and (
                        parent.kind == 'index' and position == 0 or
                        parent.kind == 'call' and parent.value in READ | {'clone', 'managed'} and parent.value not in self.names or
                        parent.kind == 'fold' and position == 0 or
                        parent.kind == 'for' and position == 0 or
                        parent.kind == 'invoke' and position == 0 and closure)
                    if not ok:
                        valid = False
                for attr in ('args', 'body', 'other'):
                    for i, child in enumerate(getattr(n, attr, [])):
                        uses(child, n, i)
            for statement in f.body:
                uses(statement)
            amount = max(1, size or 0) * (1 if typ == '[bool]' else 8) if not closure else max(1, len(e.target)) * 8
            valid = valid and (closure or 0 <= size <= 128) and amount <= budget
            accepted = valid and (self.enabled and 'stack' in self.features or self.required)
            self.report(e, 'stack', accepted, 'bounded storage, no escaping uses' if accepted else 'disabled, escaping/unknown use, or stack budget exceeded')
            if accepted:
                self.stack[id(e)] = size if not closure else 'closure'
                budget -= amount
                if closure:
                    for n in nodes:
                        if n.kind == 'invoke' and n.args[0].kind == 'name' and n.args[0].value == name:
                            self.direct[id(n)] = e
                            self.report(n, 'callback', True, 'single immutable local closure target')
            if size is not None and valid and self.enabled and 'bounds' in self.features:
                # Constant index proof remains valid: accepted use grammar forbids
                # descriptor reassignment, aliases, pointer extraction and calls.
                for n in nodes:
                    if n.kind == 'index' and n.args[0].kind == 'name' and n.args[0].value == name:
                        i = n.args[1]
                        if i.kind == 'i64' and 0 <= int(i.value) < size:
                            self.unchecked.add(id(n))
                            self.report(n, 'bounds', True, 'constant index in immutable descriptor extent')
        for s in nodes:
            if s.kind != 'var' or s.value[1] not in {'[i64]', '[f64]', '[bool]'}:
                continue
            name = s.value[0]
            initial = s.args[0]
            fresh = initial.kind == 'array' or initial.kind == 'call' and initial.value in {'fill', 'range', 'clone', 'managed'}
            if not fresh or bindings[name] != 1:
                self.report(initial, 'reuse', False, 'initial storage may alias or binding name is reused')
                continue
            replacements = []
            valid = True
            def reusable(n, parent=None, pos=0):
                nonlocal valid
                if n.kind == 'lambda' and any(k == name for k, _ in n.target):
                    valid = False
                if n.kind == 'set' and n.args[0].kind == 'name' and n.args[0].value == name:
                    rhs = n.args[1]
                    if n.value == '=' and rhs.kind == 'call' and rhs.value == 'fill':
                        replacements.append(rhs)
                    else:
                        valid = False
                if n.kind == 'name' and n.value == name:
                    if not parent or not (parent.kind == 'set' and pos == 0 or
                        parent.kind == 'index' and pos == 0 or
                        parent.kind == 'call' and parent.value in READ and parent.value not in self.names or
                        parent.kind in {'for', 'fold'} and pos == 0):
                        valid = False
                for attr in ('args', 'body', 'other'):
                    for i, child in enumerate(getattr(n, attr, [])):
                        reusable(child, n, i)
            for root in f.body:
                reusable(root)
            for rhs in replacements:
                accepted = valid and (self.enabled and 'reuse' in self.features or self.required)
                self.report(rhs, 'reuse', accepted, 'private primitive buffer; reuse only on equal length' if accepted else 'alias/escape or disabled')
                if accepted:
                    self.reuse[id(rhs)] = name
        for n in nodes:
            if n.kind == 'call' and n.value in {'sum', 'count'} and n.value not in self.names:
                a = n.args[0]
                if a.kind == 'call' and a.value in {'fill', 'range'} and a.typ in {'[i64]', '[f64]', '[bool]'}:
                    if self.enabled and 'fusion' in self.features or self.required:
                        self.fused.add(id(n))
                        self.elided.add(id(a))
                        self.report(n, 'fusion', True, 'construction arguments evaluated once; checked reduction in index order')
            if n.kind == 'binary'  and n.typ == 'i64' and n.value in {'+', '-', '*'}:
                if all(a.kind == 'i64' for a in n.args):
                    a, b = (int(x.value) for x in n.args)
                    v = {'+': lambda:a+b, '-':lambda:a-b, '*':lambda:a*b}[n.value]()
                    if -(2**63) <= v < 2**63 and self.enabled and 'overflow' in self.features:
                        self.unchecked.add(id(n))
                        self.report(n, 'overflow', True, 'literal interval lies within signed i64')

    def summarize(self, f, active):
        key = id(f)
        if key in active:
            return Summary(True, True, True, True, True, True, ['recursive call graph'])
        if key in self.summaries:
            return self.summaries[key]
        s = Summary(alias=f.result not in SCALAR | {'void'}, escape=f.result not in SCALAR | {'void'})
        for region in self.ir[id(f)]:
            for n in region_nodes(region):
                if n.kind == 'name' and n.typ not in SCALAR | {'void'}:
                    s.alias = True
                if n.kind in {'index', 'unary', 'fold', 'reduce'} or n.kind == 'binary' and n.value in {'+', '-', '*', '/', '%'}:
                    s.effects = True
                if n.kind == 'set':
                    s.mutation = True
                    if n.args[0].kind != 'name':
                        s.escape = True
                if n.kind in {'unsafe', 'scope'}:
                    s.effects = True
                if n.kind == 'for' and not n.args[0].typ.startswith('['):
                    s.heap = True
                    s.reasons.append('collection snapshot')
                if n.kind == 'array' or n.kind == 'lambda' and n.target:
                    if id(n) not in self.stack and id(n) not in self.elided:
                        s.heap = True
                        s.reasons.append('array/closure allocation')
                if n.kind in {'call', 'method_call', 'invoke'}:
                    target = n.target if isinstance(n.target, Function) else self.names.get(n.value) if n.kind == 'call' else None
                    if target:
                        other = self.summarize(target, active | {key})
                        s.merge(other)
                        if other.heap:
                            s.reasons.append('call ' + target.name)
                    elif n.kind == 'invoke' and id(n) in self.direct:
                        pass # Lambda body is visited above; unknown nested calls remain top.
                    elif n.kind == 'call' and n.value in self.records or n.kind == 'method_call' and isinstance(n.target, tuple):
                        s.alias = True
                    elif n.kind == 'call' and n.value in NOHEAP:
                        s.effects |= n.value in {'clock', 'argi', 'free', 'move'}
                    elif n.kind == 'call' and n.value in ALLOC:
                        if id(n) not in self.stack and id(n) not in self.elided:
                            s.heap = True
                            s.reasons.append(n.value)
                        s.alias |= n.value in {'clone', 'push'}
                    else:
                        s.merge(Summary(True, True, True, True, True, True))
                        s.reasons.append('unknown/runtime effect ' + str(n.value))
        s.effects |= s.heap
        s.reasons = sorted(set(s.reasons))
        self.summaries[key] = s
        return s

    def report_data(self):
        return {'functions': {((f.owner + '.') if f.owner else '') + f.name: asdict(self.summaries[id(f)]) for f in self.functions},
                'transformations': self.reports,
                'limits': ['4096 byte estimated stack budget per function; scalar arrays <=128 elements',
                           'recursive and unknown calls are conservative',
                           'reuse limited to unaliased primitive fills; fusion limited to immediate fill/range reductions']}
