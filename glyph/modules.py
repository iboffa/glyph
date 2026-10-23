"""Resolve explicit file imports and isolate each file's top-level names."""
import os
from pathlib import Path
from .syntax import Diagnostic, Import, Parser, Record, Union, Token
from .checker import BUILTINS, SCALARS
from .collections import collection_type, parts
from .abstractions import map_type


class Program(list):
    def __init__(self, declarations, paths):
        super().__init__(declarations)
        self.paths = paths


def load_program(path):
    modules = []
    active = set()
    total = 0

    def visit(path, origin=None):
        nonlocal total
        path = Path(os.path.abspath(path))
        token = origin or Token('', 1, 1, 1, str(path))
        try:
            info = path.stat()
            identity = (info.st_dev, info.st_ino)
            for i, module in enumerate(modules):
                if identity == module['identity']:
                    if i in active:
                        raise Diagnostic('G402', f'circular import of {path}', token)
                    return i
            if len(modules) >= 128:
                raise Diagnostic('G005', 'program exceeds the 128-file import limit', token)
            with path.open(encoding='utf-8', newline='') as stream:
                source = stream.read()
        except (OSError, UnicodeError, ValueError) as error:
            raise Diagnostic('G400', f'cannot read module {path}: {error}', token) from None
        total += len(source.encode('utf-8'))
        if total > 1048576:
            raise Diagnostic('G005', 'program exceeds the 1 MiB source limit', token)
        try:
            declarations = Parser(source, path).parse()
        except Diagnostic as error:
            error.token.path = str(path)
            raise
        index = len(modules)
        module = dict(path=path, identity=identity, declarations=declarations, imports=[], symbols={})
        modules.append(module)
        active.add(index)
        if index == 0 and not any(isinstance(d, Import) for d in declarations):
            active.remove(index)
            return index
        for declaration in declarations:
            if isinstance(declaration, Import):
                target = declaration.path
                if not target or '\0' in target or not target.endswith('.gly') or Path(target).is_absolute():
                    raise Diagnostic('G400', 'import path must be a relative .gly file path', declaration.token)
                dependency = visit(path.parent / target, declaration.token)
                module['imports'].append((declaration, dependency))
            else:
                name = declaration.name
                forbidden = BUILTINS | (SCALARS | {'int', 'void', 'main', 'sum', 'count', 'zip'} if isinstance(declaration, Record) else set())
                if name in module['symbols'] or name in forbidden:
                    raise Diagnostic('G103', f'duplicate or reserved declaration {name}', declaration.token)
                if index and name == 'main':
                    raise Diagnostic('G401', 'imported modules must not declare main', declaration.token)
                module['symbols'][name] = name if index == 0 and name == 'main' else f'gmod{index}_{name}'
        active.remove(index)
        return index

    visit(path)
    # Preserve names and the established API for ordinary single-file programs.
    if len(modules) == 1 and not modules[0]['imports']:
        return Program(modules[0]['declarations'], [modules[0]['path']])
    generic_symbols = {module['symbols'][d.name] for module in modules
                       for d in module['declarations'] if getattr(d, 'type_params', [])}
    result = []
    for index, module in enumerate(modules):
        bindings = dict(module['symbols'])
        for declaration, dependency in module['imports']:
            exports = modules[dependency]['symbols']
            for token in declaration.names:
                name = token.text
                if name not in exports or name == 'main':
                    raise Diagnostic('G401', f'module does not declare {name}', token)
                if name in bindings or name in BUILTINS:
                    raise Diagnostic('G401', f'import conflicts with {name}', token)
                bindings[name] = exports[name]

        def name(value):
            if value in bindings:
                return bindings[value]
            if not value or value in BUILTINS | SCALARS | {'int', 'void', 'self', 'main', 'sum', 'count', 'zip'}:
                return value
            return f'gmod{index}_{value}'

        type_bindings = set()
        def typ(value):
            return map_type(value, lambda n: n if n in type_bindings or n in {"list", "map", "set"} else name(n))

        def local(value, receiver):
            return value if receiver and value == 'self' else name(value)

        def expression(expr, receiver):
            if expr.kind == 'specialize':
                target = name(expr.value[0])
                # Brackets may still be an index; local names then belong to
                # the value namespace even if they spell a type parameter.
                bind = typ if target in generic_symbols else lambda t: map_type(t, name)
                expr.value = (target, [bind(t) for t in expr.value[1]])
            if expr.kind == 'lambda':
                params, result = expr.value
                expr.value = ([(local(n, receiver), typ(t), tok) for n, t, tok in params], typ(result))
            if expr.kind == 'call':
                expr.value = name(expr.value)
            if expr.kind == 'name':
                expr.value = local(expr.value, receiver)
            if expr.kind == 'reduce':
                for token in expr.value[1]:
                    token.text = local(token.text, receiver)
            for arg in expr.args:
                expression(arg, receiver)

        def block(body, receiver):
            for stmt in body:
                if stmt.kind == 'var':
                    stmt.value = (local(stmt.value[0], receiver), typ(stmt.value[1]))
                if stmt.kind == 'case':
                    stmt.value = (stmt.value[0], [local(n, receiver) for n in stmt.value[1]])
                if stmt.kind == 'for':
                    stmt.value = local(stmt.value, receiver)
                for arg in stmt.args:
                    expression(arg, receiver)
                block(stmt.body, receiver)
                block(stmt.other, receiver)

        def function(fn):
            receiver = bool(fn.owner) and not fn.static
            if not fn.owner:
                fn.name = name(fn.name)
            else:
                fn.owner = name(fn.owner)
            fn.params = [(local(n, receiver), typ(t), token) for n, t, token in fn.params]
            fn.result = typ(fn.result)
            block(fn.body, receiver)

        for declaration in module['declarations']:
            if isinstance(declaration, Import):
                continue
            type_bindings = {n for n, _, _ in declaration.type_params}
            declaration.type_params = [(n, name(c) if c else '', tok) for n, c, tok in declaration.type_params]
            if isinstance(declaration, Record):
                declaration.name = name(declaration.name)
                if isinstance(declaration, Union):
                    for _, fields, _ in declaration.variants:
                        for field in fields:
                            field.typ = typ(field.typ)
                for field in declaration.fields:
                    field.typ = typ(field.typ)
                for method in declaration.methods:
                    function(method)
            else:
                function(declaration)
            result.append(declaration)
    return Program(result, [m['path'] for m in modules])
