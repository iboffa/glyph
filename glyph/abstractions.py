"""Explicit monomorphization and shared structural type operations.

Templates are checked at each concrete instantiation. Expansion is bounded;
there is no runtime type erasure or generic dispatch.
"""
from copy import deepcopy
from .syntax import Diagnostic, Function, Record, Union, Interface, Field, Expr


def split_types(text):
    result, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch in '[(':
            depth += 1
        elif ch in '])':
            depth -= 1
        elif ch == ',' and depth == 0:
            result.append(text[start:i])
            start = i + 1
    if text[start:]:
        result.append(text[start:])
    return result


def fn_parts(typ):
    if not typ.startswith('fn('):
        return None
    depth = 1
    for i in range(3, len(typ)):
        if typ[i] == '(':
            depth += 1
        elif typ[i] == ')':
            depth -= 1
            if depth == 0:
                return split_types(typ[3:i]), typ[i + 2:]
    return None


def map_type(typ, leaf, application=None):
    if not typ:
        return typ
    fn = fn_parts(typ)
    if fn:
        args, result = fn
        return 'fn(' + ','.join(map_type(t, leaf, application) for t in args) + ')>' + map_type(result, leaf, application)
    if typ.startswith('['):
        return '[' + map_type(typ[1:-1], leaf, application) + ']'
    if typ.startswith('*'):
        return '*' + map_type(typ[1:], leaf, application)
    if '[' in typ:
        name, rest = typ.split('[', 1)
        args = [map_type(t, leaf, application) for t in split_types(rest[:-1])]
        return application(name, args) if application else leaf(name) + '[' + ','.join(args) + ']'
    return leaf(typ)


class Expansion:
    def __init__(self, declarations):
        self.original = declarations
        self.templates = {}
        self.interfaces = {}
        self.instances = {}
        self.constraints = []
        self.arguments = []
        self.output = []
        self.used = {d.name for d in declarations if hasattr(d, 'name')}
        self.depth = 0
        from .checker import BUILTINS, SCALARS
        seen = set()
        for d in declarations:
            if not isinstance(d, (Record, Function)):
                continue
            if d.name in seen:
                raise Diagnostic('G103', f'duplicate declaration {d.name}', d.token)
            seen.add(d.name)
            if d.type_params or isinstance(d, Interface):
                if d.name in BUILTINS | SCALARS | {'int', 'void', 'main', 'sum', 'count', 'zip'}:
                    raise Diagnostic('G103', f'reserved template/interface name {d.name}', d.token)
            params = set()
            for name, constraint, token in d.type_params:
                if name in params or name in BUILTINS | SCALARS | {'int', 'void', 'self', d.name}:
                    raise Diagnostic('G103', f'duplicate or reserved type parameter {name}', token)
                params.add(name)
            if isinstance(d, Interface):
                if d.type_params:
                    raise Diagnostic('G003', 'interfaces do not take type arguments', d.token)
                self.interfaces[d.name] = d
            elif d.type_params:
                self.templates[d.name] = d
            if isinstance(d, Record):
                for m in d.methods:
                    if m.type_params:
                        raise Diagnostic('G003', 'put type parameters on the enclosing record', m.token)
        for d in self.templates.values():
            for _, constraint, token in d.type_params:
                if constraint and constraint not in self.interfaces:
                    raise Diagnostic('G003', f'unknown interface {constraint}', token)

    def instantiate(self, name, args, token, expect_type=False):
        template = self.templates.get(name)
        if template is None:
            raise Diagnostic('G003', f'{name} is not a generic declaration', token)
        if expect_type and not isinstance(template, Record):
            raise Diagnostic('G003', f'{name} is a function, not a type', token)
        if len(args) != len(template.type_params):
            raise Diagnostic('G107', f'{name} expects {len(template.type_params)} type arguments', token)
        if 'void' in args:
            raise Diagnostic('G003', 'void is not a type argument', token)
        self.arguments.extend((arg, token) for arg in args)
        key = (name, tuple(args))
        if key in self.instances:
            return self.instances[key]
        if len(self.instances) >= 256 or self.depth >= 64:
            raise Diagnostic('G005', 'generic expansion limit exceeded', token)
        serial = len(self.instances)
        generated = f'_glyph_inst_{serial}'
        while generated in self.used:
            generated += '_'
        self.used.add(generated)
        self.instances[key] = generated
        instance = deepcopy(template)
        instance.name, instance.type_params = generated, []
        bindings = dict(zip((p[0] for p in template.type_params), args))
        self.constraints.extend((arg, constraint, token) for arg, (_, constraint, _) in zip(args, template.type_params) if constraint)
        self.depth += 1
        try:
            self.declaration(instance, bindings)
        finally:
            self.depth -= 1
        self.output.append(instance)
        return generated

    def typ(self, typ, bindings, token):
        def leaf(name):
            name = bindings.get(name, name)
            if name == 'int':
                return 'i64'
            if name in self.templates:
                raise Diagnostic('G003', f'{name} requires explicit type arguments', token)
            return name
        def application(name, args):
            if name in {'list', 'map', 'set', 'task', 'channel'}:
                if len(args) != (2 if name == 'map' else 1):
                    raise Diagnostic('G003', f'invalid type arguments for {name}', token)
                return name + '[' + ','.join(args) + ']'
            return self.instantiate(name, args, token, True)
        return map_type(typ, leaf, application)

    def index_expression(self, typ, token):
        if typ.isidentifier():
            return Expr('name', token, typ)
        if typ.startswith('['):
            return Expr('array', token, args=[self.index_expression(typ[1:-1], token)])
        if '[' in typ and not fn_parts(typ):
            head, args = typ.split('[', 1)
            items = split_types(args[:-1])
            if len(items) == 1:
                return Expr('index', token, args=[Expr('name', token, head), self.index_expression(items[0], token)])
        raise Diagnostic('G003', 'invalid type arguments or index', token)

    def expression(self, e, bindings):
        if e.kind == 'specialize':
            name, args = e.value
            if name not in self.templates and len(args) == 1:
                e.kind, e.value, e.args = 'index', None, [Expr('name', e.token, name), self.index_expression(args[0], e.token)]
            else:
                args = [self.typ(t, bindings, e.token) for t in args]
                e.kind, e.value = 'name', self.instantiate(name, args, e.token)
        elif e.kind == 'index' and e.args[0].kind == 'name' and e.args[0].value in self.templates:
            # A single generic argument on a function value is parsed like an index.
            arg = e.args[1]
            if arg.kind != 'name':
                raise Diagnostic('G003', 'expected an explicit type argument', arg.token)
            e.kind, e.value, e.args = 'name', self.instantiate(e.args[0].value, [self.typ(arg.value, bindings, arg.token)], e.token), []
        if e.kind == 'lambda':
            params, result = e.value
            e.value = ([(n, self.typ(t, bindings, tok), tok) for n, t, tok in params], self.typ(result, bindings, e.token))
        for arg in e.args:
            self.expression(arg, bindings)
        if e.kind == 'invoke' and e.args[0].kind == 'name':
            e.kind, e.value, e.args = 'call', e.args[0].value, e.args[1:]
        if e.kind == 'call' and e.value in self.templates:
            raise Diagnostic('G003', f'{e.value} requires explicit type arguments', e.token)

    def block(self, body, bindings):
        for s in body:
            if s.kind == 'var':
                s.value = (s.value[0], self.typ(s.value[1], bindings, s.token))
            for arg in s.args:
                self.expression(arg, bindings)
            self.block(s.body, bindings)
            self.block(s.other, bindings)

    def declaration(self, d, bindings):
        if isinstance(d, Record):
            if isinstance(d, Union):
                names = set()
                d.fields = [Field('_tag', 'i64', d.token, True)]
                for i, (name, fields, token) in enumerate(d.variants):
                    if name in names:
                        raise Diagnostic('G103', f'duplicate variant {name}', token)
                    names.add(name)
                    members = set()
                    for f in fields:
                        if f.name in members:
                            raise Diagnostic('G103', f'duplicate payload field {f.name}', f.token)
                        members.add(f.name)
                        f.typ = self.typ(f.typ, bindings, f.token)
                        d.fields.append(Field(f'_v{i}_{f.name}', f.typ, f.token, True))
                if not d.variants:
                    raise Diagnostic('G102', 'a union requires at least one variant', d.token)
            else:
                for f in d.fields:
                    f.typ = self.typ(f.typ, bindings, f.token)
            for m in d.methods:
                m.owner = d.name
                self.declaration(m, bindings)
        else:
            d.params = [(n, self.typ(t, bindings, tok), tok) for n, t, tok in d.params]
            d.result = self.typ(d.result, bindings, d.token)
            self.block(d.body, bindings)

    def run(self):
        for interface in self.interfaces.values():
            self.declaration(interface, {})
        for d in self.original:
            if isinstance(d, Interface) or getattr(d, 'type_params', []):
                continue
            self.declaration(d, {})
            self.output.append(d)
        self.original[:] = self.output
        return self
