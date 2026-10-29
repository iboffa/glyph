"""Static types, lexical scopes, return analysis and unsafe boundaries."""
import math
from .syntax import Diagnostic, Function, Record, Union, Import
from .abstractions import Expansion, fn_parts, map_type
from .gui import GUI_SIGNATURES
from .stdlib import STD_SIGNATURES, RESULT_TYPES, result_records
from .concurrency import NAMES, analyze, safe_type
from .collections import KINDS, KEYS, collection_type, parts, method_signature

SCALARS = {"i64", "f64", "bool", "str"}
BUILTINS = {"arena_fill", "owned_fill", "free", "move", "managed", "print", "len", "range", "fill", "clone", "push", "argi", "clock", "ptr", "load", "store", "offset", "f64", "i64"}
BUILTINS |= GUI_SIGNATURES.keys()
BUILTINS |= STD_SIGNATURES.keys()
BUILTINS |= RESULT_TYPES.keys()
BUILTINS |= KINDS | NAMES

def canonical_type(typ):
    return map_type(typ, lambda t: "i64" if t == "int" else t)


class Checker:
    def __init__(self, functions):
        self.expansion = Expansion(functions).run()
        self.declarations = functions
        self.functions = [f for f in functions if isinstance(f, Function)]
        self.records = result_records()
        self.methods = {}
        self.signatures = {}
        self.inferring = set()
        self.current = None

    def environment(self, f):
        env = {name: typ for name, typ, _ in f.params}
        if f.owner and not f.static:
            env["self"] = f.owner
        return env

    def validate_type(self, typ, token):
        typ = canonical_type(typ)
        if typ.startswith("channel["):
            self.validate_type(typ[8:-1], token)
            if not safe_type(typ[8:-1], self.records):
                raise Diagnostic("G116", "channel payload must be recursively share-safe", token)
            return typ
        if typ.startswith("buffer["):
            raise Diagnostic("G121", "owned buffers are inferred primitive local bindings only", token)
        if typ.startswith("task["):
            raise Diagnostic("G117", "task handles are inferred local bindings only", token)
        fn = fn_parts(typ)
        if fn:
            args, result = fn
            for item in args:
                if self.validate_type(item, token) == "void":
                    raise Diagnostic("G003", "function parameter cannot be void", token)
            self.validate_type(result, token)
            return typ
        valid = typ in SCALARS | {"void"} or typ in self.records
        if typ.startswith("["):
            valid = typ[1:-1] in SCALARS or typ[1:-1] in self.records or bool(fn_parts(typ[1:-1]))
            if fn_parts(typ[1:-1]):
                self.validate_type(typ[1:-1], token)
        if typ.startswith("*"):
            valid = typ[1:] in {"i64", "f64", "bool"}
        if collection_type(typ):
            kind, items = parts(typ)
            valid = all(t in SCALARS or t in self.records or bool(fn_parts(t)) for t in items)
            for item in items:
                if fn_parts(item):
                    self.validate_type(item, token)
            if kind != 'list':
                valid = valid and items[0] in KEYS
        if not valid:
            raise Diagnostic("G003", f"unknown or unsupported type {typ}", token)
        return typ

    def private_access(self, owner, private, node):
        if private and (self.current is None or self.current.owner != owner):
            self.fail("G112", f"private member of {owner} is only accessible inside its methods", node)

    def writable(self, e):
        if e.kind in {"name", "index"}:
            root = e
        elif e.kind == "field":
            self.writable(e.args[0])
            return
        else:
            self.fail("G104", "mutation requires a variable, array element or addressable field", e)
        # Arrays are shared references; mutating their elements is independent
        # of replacing a field in the enclosing value record.
        if root.kind == "name" and root.value == "self" and self.current and self.current.owner:
            if not self.current.mut and not self.current.static:
                self.fail("G112", "updating self or its value fields requires a mut method", e)

    def result_type(self, f):
        if f.result:
            return f.result
        key = (f.owner, f.name)
        if key in self.inferring:
            self.fail("G111", f"cannot infer recursive result of {f.name}; add a result type", f)
        self.inferring.add(key)
        previous, self.current = self.current, f
        try:
            f.result = self.expr(f.body[0].args[0], self.environment(f), False)
        finally:
            self.current = previous
            self.inferring.remove(key)
        return f.result

    def fail(self, code, text, node):
        raise Diagnostic(code, text, node.token)

    def same(self, actual, expected, node):
        if actual != expected:
            self.fail("G102", f"expected {expected}, found {actual}", node)

    def check(self):
        for declaration in self.declarations:
            if isinstance(declaration, Import):
                self.fail("G400", "resolve imports with glyph.modules.load_program(path)", declaration)
        for record in self.declarations:
            if not isinstance(record, Record):
                continue
            if record.name in self.records or record.name in BUILTINS | SCALARS | {"int", "void", "main", "sum", "count", "zip"}:
                self.fail("G103", f"duplicate or reserved type {record.name}", record)
            self.records[record.name] = record
        for record in self.records.values():
            if not record.fields:
                self.fail("G102", "a value record requires at least one field", record)
            names = set()
            for member in [*record.fields, *record.methods]:
                if member.name in names:
                    self.fail("G103", f"duplicate member {member.name} in {record.name}", member)
                names.add(member.name)
            for field in record.fields:
                field.typ = self.validate_type(field.typ, field.token)
                if field.typ == "void":
                    self.fail("G102", "field cannot have type void", field)
            for method in record.methods:
                self.methods[(record.name, method.name)] = method
                self.functions.append(method)
        # A direct record field embeds its value. Array fields embed only a
        # descriptor, so recursive arrays do not create infinitely sized values.
        visiting, complete = set(), set()
        def layout(name):
            if name in visiting:
                self.fail("G113", f"recursive value layout for {name}; use an array indirection", self.records[name])
            if name in complete:
                return
            visiting.add(name)
            for field in self.records[name].fields:
                if field.typ in self.records:
                    layout(field.typ)
            visiting.remove(name)
            complete.add(name)
        for name in self.records:
            layout(name)
        for f in self.functions:
            if not f.owner:
                if f.name in self.signatures or f.name in BUILTINS or f.name in self.records:
                    self.fail("G103", f"duplicate or reserved function {f.name}", f)
                self.signatures[f.name] = f
            f.result = self.validate_type(f.result, f.token) if f.result else ""
            f.params = [(n, self.validate_type(t, token), token) for n, t, token in f.params]
            seen = {"self"} if f.owner and not f.static else set()
            for name, typ, token in f.params:
                if name in seen or typ == "void":
                    raise Diagnostic("G103", "duplicate parameter or void parameter type", token)
                seen.add(name)
        self.check_interfaces()
        main = self.signatures.get("main")
        if main is None:
            from .syntax import Token
            raise Diagnostic("G108", "program requires main>i64 or main>void", Token("", 1, 1, 1))
        if main.params or self.result_type(main) not in {"i64", "void"}:
            self.fail("G108", "main must have no parameters and return i64 or void", main)
        for f in self.functions:
            self.result_type(f)
            self.current = f
            returns = self.block(f.body, self.environment(f), f.result, False)
            if f.result != "void" and not returns:
                self.fail("G106", "not every path returns a value", f)
        self.current = None
        analyze(self)
        from .memory import validate
        from .analysis import Analysis
        validate(self)
        Analysis(self.declarations)
        return self.declarations

    def check_interfaces(self):
        for actual, token in self.expansion.arguments:
            self.validate_type(actual, token)
        for interface in self.expansion.interfaces.values():
            names = set()
            if not interface.methods:
                self.fail("G102", "an interface requires at least one method", interface)
            for method in interface.methods:
                if method.name in names:
                    self.fail("G103", "duplicate interface method", method)
                names.add(method.name)
                method.result = self.validate_type(method.result, method.token)
                method.params = [(n, self.validate_type(t, tok), tok) for n, t, tok in method.params]
                if len({n for n, _, _ in method.params}) != len(method.params):
                    self.fail("G103", "duplicate interface parameter", method)
                if any(t == "void" for _, t, _ in method.params):
                    self.fail("G103", "void interface parameter", method)
        for actual, constraint, token in self.expansion.constraints:
            self.validate_type(actual, token)
            for required in self.expansion.interfaces[constraint].methods:
                method = self.methods.get((actual, required.name))
                if (method is None or method.static or method.private or method.mut != required.mut
                        or [t for _, t, _ in method.params] != [t for _, t, _ in required.params]
                        or self.result_type(method) != required.result):
                    raise Diagnostic("G114", f"{actual} does not satisfy {constraint}.{required.name}", token)

    def invoke(self, e, args, typ, env, unsafe):
        signature = fn_parts(typ)
        if signature is None:
            self.fail("G102", f"{typ} is not callable", e)
        params, result = signature
        if len(args) != len(params):
            self.fail("G107", f"function value expects {len(params)} arguments", e)
        for arg, param in zip(args, params):
            self.same(self.expr(arg, env, unsafe, param), param, arg)
        return result

    def block(self, body, env, result, unsafe):
        returned = False
        for s in body:
            if returned:
                self.fail("G109", "unreachable statement", s)
            if s.kind == "var":
                name, typ = s.value
                typ = self.validate_type(typ, s.token) if typ else ""
                if name in env:
                    self.fail("G103", f"variable {name} already exists; shadowing is forbidden", s)
                actual = self.expr(s.args[0], env, unsafe, typ or None)
                typ = typ or actual
                if typ == "void":
                    self.fail("G102", "variable cannot have type void", s)
                self.same(actual, typ, s.args[0])
                s.value = (name, typ)
                env[name] = typ
            elif s.kind == "set":
                target, value = s.args
                typ = self.expr(target, env, unsafe)
                self.writable(target)
                if target.kind == "index" and target.args[0].typ == "str":
                    self.fail("G104", "strings are immutable", target)
                self.same(self.expr(value, env, unsafe, typ), typ, value)
                if s.value != "=" and (typ not in {"i64", "f64"} or s.value == "%=" and typ != "i64"):
                    self.fail("G102", "compound assignment requires compatible numeric types", s)
            elif s.kind == "ret":
                typ = self.expr(s.args[0], env, unsafe, result) if s.args else "void"
                self.same(typ, result, s)
                returned = True
            elif s.kind == "expr":
                self.expr(s.args[0], env, unsafe)
                if s.args[0].kind not in {"call", "reduce", "method_call", "invoke"}:
                    self.fail("G104", "expression statement must be a function call", s)
            elif s.kind in {"if", "while"}:
                self.same(self.expr(s.args[0], env, unsafe), "bool", s.args[0])
                a = self.block(s.body, env.copy(), result, unsafe)
                b = self.block(s.other, env.copy(), result, unsafe) if s.other else False
                returned = s.kind == "if" and a and b
            elif s.kind == "for":
                typ = self.expr(s.args[0], env, unsafe)
                if not typ.startswith("[") and not collection_type(typ):
                    self.fail("G102", "for requires an array or collection", s.args[0])
                if s.value in env:
                    self.fail("G103", "loop variable shadows an existing variable", s)
                inner = env.copy()
                inner[s.value] = parts(typ)[1][0] if collection_type(typ) else typ[1:-1]
                self.block(s.body, inner, result, unsafe)
            elif s.kind == "match":
                typ = self.expr(s.args[0], env, unsafe)
                union = self.records.get(typ)
                if not isinstance(union, Union):
                    self.fail("G102", "match requires a tagged union", s)
                seen, all_return = set(), True
                for arm in s.body:
                    name, bindings = arm.value
                    variant = next(((i, fields) for i, (v, fields, _) in enumerate(union.variants) if v == name), None)
                    if variant is None or name in seen:
                        self.fail("G115", f"unknown or duplicate case {name}", arm)
                    seen.add(name)
                    index, fields = variant
                    if len(bindings) != len(fields):
                        self.fail("G107", f"{name} binds {len(fields)} payload values", arm)
                    inner = env.copy()
                    for binding, field in zip(bindings, fields):
                        if binding in inner:
                            self.fail("G103", "case binding shadows an existing variable", arm)
                        inner[binding] = field.typ
                    arm.target = (index, fields)
                    all_return = self.block(arm.body, inner, result, unsafe) and all_return
                if len(seen) != len(union.variants):
                    self.fail("G115", "match must cover every variant", s)
                returned = all_return
            elif s.kind == "borrow":
                typ = self.expr(s.args[0], env, unsafe)
                if not typ.startswith("buffer[") or s.value in env:
                    self.fail("G121", "borrow needs an owned buffer and a fresh binding", s)
                inner = env.copy()
                inner[s.value] = "[" + typ[7:-1] + "]"
                returned = self.block(s.body, inner, result, unsafe)
            elif s.kind == "arena":
                returned = self.block(s.body, env.copy(), result, unsafe)
            elif s.kind == "scope":
                returned = self.block(s.body, env.copy(), result, unsafe)
            elif s.kind == "unsafe":
                returned = self.block(s.body, env.copy(), result, True)
        return returned

    def expr(self, e, env, unsafe, expected=None):
        k = e.kind
        if k in SCALARS:
            typ = k
            if k == "i64" and int(e.value) > 9223372036854775807:
                self.fail("G105", "integer literal exceeds i64", e)
            if k == "f64" and not math.isfinite(float(e.value)):
                self.fail("G105", "floating literal must be finite", e)
        elif k == "name":
            if e.value in env:
                typ = env[e.value]
            elif e.value in self.signatures and e.value != "main":
                f = self.signatures[e.value]
                typ = 'fn(' + ','.join(t for _, t, _ in f.params) + ')>' + self.result_type(f)
                e.target = f
            else:
                self.fail("G101", f"unknown variable {e.value}", e)
        elif k == "array":
            item = expected[1:-1] if expected and expected.startswith("[") else None
            if not e.args and item is None:
                self.fail("G102", "empty array requires an expected array type", e)
            for arg in e.args:
                found = self.expr(arg, env, unsafe, item)
                if item is None:
                    item = found
                self.same(found, item, arg)
            if item not in SCALARS and item not in self.records and not fn_parts(item):
                self.fail("G102", "arrays contain scalar, record, union or function values only", e)
            typ = f"[{item}]"
        elif k == "unary":
            # The minimum signed value is a single literal semantically.
            if e.value == "-" and e.args[0].kind == "i64" and int(e.args[0].value) == 9223372036854775808:
                e.kind, e.value, e.args = "i64", "-9223372036854775808", []
                typ = "i64"
            else:
                typ = self.expr(e.args[0], env, unsafe)
                if e.value == "not":
                    self.same(typ, "bool", e)
                elif typ not in {"i64", "f64"}:
                    self.fail("G102", "negation requires a number", e)
        elif k == "binary":
            a, b = [self.expr(x, env, unsafe) for x in e.args]
            self.same(b, a, e)
            if e.value in {"and", "or"}:
                self.same(a, "bool", e)
                typ = "bool"
            elif e.value in {"==", "!="}:
                if a not in SCALARS:
                    self.fail("G102", "equality requires scalar operands", e)
                typ = "bool"
            elif e.value in {"<", "<=", ">", ">="}:
                if a not in {"i64", "f64"}:
                    self.fail("G102", "ordering requires numbers", e)
                typ = "bool"
            else:
                if a not in {"i64", "f64"} or e.value == "%" and a != "i64":
                    self.fail("G102", "arithmetic requires compatible numbers", e)
                typ = a
        elif k == "index":
            base = self.expr(e.args[0], env, unsafe)
            self.same(self.expr(e.args[1], env, unsafe), "i64", e.args[1])
            if not base.startswith("["):
                self.fail("G102", "indexing requires an array", e)
            typ = base[1:-1]
        elif k == "field":
            base = self.expr(e.args[0], env, unsafe)
            record = self.records.get(base)
            field = next((f for f in record.fields if f.name == e.value), None) if record and not isinstance(record, Union) else None
            if field is None:
                self.fail("G101", f"no field {e.value} on {base}", e)
            self.private_access(base, field.private, e)
            typ = field.typ
        elif k == "method_call":
            base = e.args[0]
            static = base.kind == "name" and base.value in self.records and base.value not in env
            owner = base.value if static else self.expr(base, env, unsafe)
            union = self.records.get(owner)
            if static and isinstance(union, Union):
                variant = next(((i, fields) for i, (name, fields, _) in enumerate(union.variants) if name == e.value), None)
                if variant is None:
                    self.fail("G101", f"no variant {e.value} on {owner}", e)
                index, fields = variant
                if len(e.args) - 1 != len(fields):
                    self.fail("G107", f"{e.value} expects {len(fields)} payload values", e)
                for arg, field in zip(e.args[1:], fields):
                    self.same(self.expr(arg, env, unsafe, field.typ), field.typ, arg)
                e.target, e.typ = (union, index, fields), owner
                return owner
            if not static and owner in self.records:
                field = next((f for f in self.records[owner].fields if f.name == e.value), None)
                if field and fn_parts(field.typ):
                    from .syntax import Expr
                    callee = Expr("field", e.token, e.value, [base])
                    e.kind, e.args = "invoke", [callee] + e.args[1:]
                    return self.expr(e, env, unsafe, expected)
            if collection_type(owner):
                sig = method_signature(owner, e.value)
                if sig is None:
                    self.fail("G101", f"no method {e.value} on {owner}", e)
                params, result = sig
                if len(e.args) - 1 != len(params):
                    self.fail("G107", f"{e.value} expects {len(params)} arguments", e)
                for arg, param in zip(e.args[1:], params):
                    self.same(self.expr(arg, env, unsafe, param), param, arg)
                e.typ = result
                return result
            method = self.methods.get((owner, e.value))
            if method is None:
                self.fail("G101", f"no method {e.value} on {owner}", e)
            if static != method.static:
                self.fail("G104", "static methods require a type; instance methods require a value", e)
            self.private_access(owner, method.private, e)
            if method.mut:
                self.writable(base)
            if len(e.args) - 1 != len(method.params):
                self.fail("G107", f"{owner}.{e.value} expects {len(method.params)} arguments", e)
            for arg, (_, param_type, _) in zip(e.args[1:], method.params):
                self.same(self.expr(arg, env, unsafe, param_type), param_type, arg)
            e.target = method
            typ = self.result_type(method)
        elif k == "fold":
            base = self.expr(e.args[0], env, unsafe)
            if base not in {"[i64]", "[f64]"}:
                self.fail("G102", "fold requires a numeric array", e)
            typ = base[1:-1]
            self.same(self.expr(e.args[1], env, unsafe), typ, e.args[1])
        elif k == "reduce":
            name, bindings, zipped = e.value
            sources = e.args[1:]
            if len(bindings) != len(sources) or zipped and len(sources) < 2:
                self.fail("G107", "zip requires at least two arrays and one binding per array", e)
            # Sources are evaluated in the enclosing scope, before any bindings.
            types = [self.expr(source, env, unsafe) for source in sources]
            inner = env.copy()
            for binding, source, array_type in zip(bindings, sources, types):
                if not array_type.startswith("["):
                    self.fail("G102", "reduction iteration requires an array", source)
                if binding.text in inner:
                    raise Diagnostic("G103", "reduction binding shadows an existing variable", binding)
                inner[binding.text] = array_type[1:-1]
            item_type = self.expr(e.args[0], inner, unsafe)
            if name == "count":
                self.same(item_type, "bool", e.args[0])
                typ = "i64"
            else:
                if item_type not in {"i64", "f64"}:
                    self.fail("G102", "sum requires numeric values", e.args[0])
                typ = item_type
        elif k == "lambda":
            params, result = e.value
            result = self.validate_type(result, e.token)
            inner = env.copy()
            for name, param, token in params:
                self.validate_type(param, token)
                if name in inner or param == "void":
                    raise Diagnostic("G103", "duplicate/shadowed lambda parameter or void type", token)
                inner[name] = param
            # Only free local names are captured, including those used by nested lambdas.
            used = set()
            def free(node, bound):
                if node.kind in {"name", "call"} and node.value in env and node.value not in bound:
                    used.add(node.value)
                nested = bound
                if node.kind == "lambda":
                    nested = bound | {n for n, _, _ in node.value[0]}
                for child in node.args:
                    free(child, nested)
            free(e.args[0], {n for n, _, _ in params})
            self.same(self.expr(e.args[0], inner, False, result), result, e.args[0])
            e.target = [(n, t) for n, t in env.items() if n in used]
            typ = 'fn(' + ','.join(t for _, t, _ in params) + ')>' + result
        elif k == "invoke":
            typ = self.invoke(e, e.args[1:], self.expr(e.args[0], env, unsafe), env, unsafe)
        elif k == "call":
            if e.value in env:
                from .syntax import Expr
                e.kind, e.args = "invoke", [Expr("name", e.token, e.value)] + e.args
                return self.expr(e, env, unsafe, expected)
            typ = self.call(e, env, unsafe, expected)
        else:
            raise AssertionError(k)
        e.typ = typ
        return typ

    def call(self, e, env, unsafe, expected):
        name = e.value
        if name in {"arena_fill", "owned_fill", "free", "move", "managed"}:
            if len(e.args) != (2 if name.endswith("_fill") else 1):
                self.fail("G107", "wrong memory operation arity", e)
            types = [self.expr(a, env, unsafe) for a in e.args]
            if name.endswith("_fill"):
                if types[0] != "i64" or types[1] not in {"i64", "f64", "bool"}:
                    self.fail("G121", "explicit storage supports int, f64 and bool only; managed references are unsupported", e)
                return ("buffer[" if name == "owned_fill" else "[") + types[1] + "]"
            if name == "managed":
                if types[0] not in {"[i64]", "[f64]", "[bool]"}:
                    self.fail("G121", "managed expects a primitive array", e)
                return types[0]
            if not types[0].startswith("buffer["):
                self.fail("G121", "move/free require an owned buffer", e)
            return types[0] if name == "move" else "void"
        if name == "channel":
            if len(e.args) != 1:
                self.fail("G107", "channel expects capacity", e)
            self.same(self.expr(e.args[0], env, unsafe), "i64", e)
            if not expected or not expected.startswith('channel['):
                self.fail("G102", "channel constructor requires channel[T] context", e)
            return self.validate_type(expected, e.token)
        if name in {"send", "receive", "close"}:
            if len(e.args) != (1 if name == 'close' else 2):
                self.fail("G107", "wrong channel operation arity", e)
            channel = self.expr(e.args[0], env, unsafe)
            if not channel.startswith('channel['):
                self.fail("G102", "expected channel", e)
            item = channel[8:-1]
            if name == 'send':
                self.same(self.expr(e.args[1], env, unsafe, item), item, e.args[1])
            if name == 'receive':
                self.same(self.expr(e.args[1], env, unsafe), 'fn(' + item + ')>void', e.args[1])
            return 'void' if name == 'close' else 'bool'
        if name == "spawn":
            if len(e.args) != 1:
                self.fail("G107", "spawn expects one zero-argument callback", e)
            sig = fn_parts(self.expr(e.args[0], env, unsafe))
            if not sig or sig[0] or not safe_type(sig[1], self.records, True):
                self.fail("G116", "spawn requires zero-argument callback with share-safe non-void result", e)
            return 'task[' + sig[1] + ']'
        if name in {"wait", "task_status"}:
            if len(e.args) != 1:
                self.fail("G107", name + " expects one task handle", e)
            typ = self.expr(e.args[0], env, unsafe)
            if not typ.startswith('task['):
                self.fail("G117", "expected task handle", e)
            return 'IntResult' if name == 'task_status' else typ[5:-1]
        if name == "par_map":
            if len(e.args) != 2:
                self.fail("G107", "par_map expects an array and callback", e)
            source = self.expr(e.args[0], env, unsafe)
            callback = self.expr(e.args[1], env, unsafe)
            sig = fn_parts(callback)
            if source not in {"[i64]", "[f64]"} or not sig or sig[0] != [source[1:-1]] or sig[1] not in {"i64", "f64"}:
                self.fail("G102", "par_map requires numeric array and matching numeric callback", e)
            return '[' + sig[1] + ']'
        if name in KINDS:
            arity = 2 if name == 'map' else 1
            if len(e.args) != arity:
                self.fail("G107", f"{name} expects {arity} arrays", e)
            hints = parts(expected)[1] if expected and expected.startswith(name + '[') else [None] * arity
            items = []
            for arg, hint in zip(e.args, hints):
                typ = self.expr(arg, env, unsafe, f'[{hint}]' if hint else None)
                if not typ.startswith('['):
                    self.fail("G102", f"{name} requires arrays", arg)
                items.append(typ[1:-1])
            if name != 'list' and items[0] not in KEYS:
                self.fail("G102", "map/set keys must be int, bool or str", e)
            return name + '[' + ','.join(items) + ']'
        if name in GUI_SIGNATURES or name in STD_SIGNATURES:
            params, result = (GUI_SIGNATURES | STD_SIGNATURES)[name]
            if len(e.args) != len(params):
                self.fail("G107", f"{name} expects {len(params)} arguments", e)
            for arg, typ in zip(e.args, params):
                self.same(self.expr(arg, env, unsafe, typ), typ, arg)
            return result
        if name in self.records:
            record = self.records[name]
            if isinstance(record, Union):
                self.fail("G104", "construct a union through a named variant", e)
            self.private_access(name, any(f.private for f in record.fields), e)
            if len(e.args) != len(record.fields):
                self.fail("G107", f"{name} expects {len(record.fields)} field values", e)
            for arg, field in zip(e.args, record.fields):
                self.same(self.expr(arg, env, unsafe, field.typ), field.typ, arg)
            e.target = record
            return name
        if name in self.signatures:
            f = self.signatures[name]
            if name == "main":
                self.fail("G104", "main cannot be called", e)
            if len(e.args) != len(f.params):
                self.fail("G107", f"{name} expects {len(f.params)} arguments", e)
            for arg, (_, typ, _) in zip(e.args, f.params):
                self.same(self.expr(arg, env, unsafe, typ), typ, arg)
            return self.result_type(f)
        arity = {"print": 1, "len": 1, "range": 1, "fill": 2, "clone": 1, "push": 2,
                 "argi": 1, "clock": 0, "ptr": 1, "load": 1, "store": 2, "offset": 2, "i64": 1, "f64": 1,
                 "sum": 1, "count": 1}
        if name not in arity:
            self.fail("G101", f"unknown function {name}", e)
        if len(e.args) != arity[name]:
            self.fail("G107", f"{name} expects {arity[name]} arguments", e)
        if name in {"ptr", "load", "store", "offset"} and not unsafe:
            self.fail("G110", f"{name} requires an unsafe block", e)
        types = [self.expr(x, env, unsafe) for x in e.args]
        if name == "sum" and types[0] in {"[i64]", "[f64]"}:
            return types[0][1:-1]
        if name == "count" and types[0] == "[bool]":
            return "i64"
        if name == "print" and types[0] in SCALARS:
            return "void"
        if name == "clock":
            return "f64"
        if name in {"range", "argi"}:
            self.same(types[0], "i64", e)
            return "[i64]" if name == "range" else "i64"
        if name == "len" and (types[0].startswith("[") or types[0] == "str" or collection_type(types[0])):
            return "i64"
        if name == "fill" and types[0] == "i64" and (types[1] in SCALARS or types[1] in self.records or fn_parts(types[1])):
            return f"[{types[1]}]"
        if name == "clone" and (types[0].startswith("[") or collection_type(types[0])):
            return types[0]
        if name == "push" and types[0].startswith("[") and types[0][1:-1] == types[1]:
            return types[0]
        if name == "ptr" and types[0] in {"[i64]", "[f64]", "[bool]"}:
            return "*" + types[0][1:-1]
        if name in {"load", "offset", "store"} and types[0].startswith("*"):
            if name == "load":
                return types[0][1:]
            self.same(types[1], "i64" if name == "offset" else types[0][1:], e)
            return types[0] if name == "offset" else "void"
        if name in {"i64", "f64"} and types[0] in {"i64", "f64"}:
            return name
        self.fail("G102", f"invalid argument types for {name}: {', '.join(types)}", e)


def check(functions):
    return Checker(functions).check()
