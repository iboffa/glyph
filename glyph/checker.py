"""Static types, lexical scopes, return analysis and unsafe boundaries."""
import math
from .syntax import Diagnostic

SCALARS = {"i64", "f64", "bool", "str"}
BUILTINS = {"print", "len", "range", "fill", "clone", "push", "argi", "clock", "ptr", "load", "store", "offset", "f64", "i64"}


class Checker:
    def __init__(self, functions):
        self.functions = functions
        self.signatures = {}

    def fail(self, code, text, node):
        raise Diagnostic(code, text, node.token)

    def same(self, actual, expected, node):
        if actual != expected:
            self.fail("G102", f"expected {expected}, found {actual}", node)

    def check(self):
        for f in self.functions:
            if f.name in self.signatures or f.name in BUILTINS:
                self.fail("G103", f"duplicate or reserved function {f.name}", f)
            self.signatures[f.name] = f
        main = self.signatures.get("main")
        if main is None:
            from .syntax import Token
            raise Diagnostic("G108", "program requires main>i64 or main>void", Token("", 1, 1, 1))
        if main.params or main.result not in {"i64", "void"}:
            self.fail("G108", "main must have no parameters and return i64 or void", main)
        for f in self.functions:
            env = {}
            for name, typ, token in f.params:
                if name in env or typ == "void":
                    raise Diagnostic("G103", "duplicate parameter or void parameter type", token)
                env[name] = typ
            returns = self.block(f.body, env, f.result, False)
            if f.result != "void" and not returns:
                self.fail("G106", "not every path returns a value", f)
        return self.functions

    def block(self, body, env, result, unsafe):
        returned = False
        for s in body:
            if returned:
                self.fail("G109", "unreachable statement", s)
            if s.kind == "var":
                name, typ = s.value
                if name in env:
                    self.fail("G103", f"variable {name} already exists; shadowing is forbidden", s)
                if typ == "void":
                    self.fail("G102", "variable cannot have type void", s)
                self.same(self.expr(s.args[0], env, unsafe, typ), typ, s.args[0])
                env[name] = typ
            elif s.kind == "set":
                target, value = s.args
                if target.kind not in {"name", "index"}:
                    self.fail("G104", "assignment requires a variable or array element", target)
                typ = self.expr(target, env, unsafe)
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
                if s.args[0].kind != "call":
                    self.fail("G104", "expression statement must be a function call", s)
            elif s.kind in {"if", "while"}:
                self.same(self.expr(s.args[0], env, unsafe), "bool", s.args[0])
                a = self.block(s.body, env.copy(), result, unsafe)
                b = self.block(s.other, env.copy(), result, unsafe) if s.other else False
                returned = s.kind == "if" and a and b
            elif s.kind == "for":
                typ = self.expr(s.args[0], env, unsafe)
                if not typ.startswith("["):
                    self.fail("G102", "for requires an array", s.args[0])
                if s.value in env:
                    self.fail("G103", "loop variable shadows an existing variable", s)
                inner = env.copy()
                inner[s.value] = typ[1:-1]
                self.block(s.body, inner, result, unsafe)
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
            if e.value not in env:
                self.fail("G101", f"unknown variable {e.value}", e)
            typ = env[e.value]
        elif k == "array":
            item = expected[1:-1] if expected and expected.startswith("[") else None
            if not e.args and item is None:
                self.fail("G102", "empty array requires an expected array type", e)
            for arg in e.args:
                found = self.expr(arg, env, unsafe, item)
                if item is None:
                    item = found
                self.same(found, item, arg)
            if item not in SCALARS:
                self.fail("G102", "arrays contain scalar values only", e)
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
        elif k == "fold":
            base = self.expr(e.args[0], env, unsafe)
            if base not in {"[i64]", "[f64]"}:
                self.fail("G102", "fold requires a numeric array", e)
            typ = base[1:-1]
            self.same(self.expr(e.args[1], env, unsafe), typ, e.args[1])
        elif k == "call":
            typ = self.call(e, env, unsafe, expected)
        else:
            raise AssertionError(k)
        e.typ = typ
        return typ

    def call(self, e, env, unsafe, expected):
        name = e.value
        if name in self.signatures:
            f = self.signatures[name]
            if name == "main":
                self.fail("G104", "main cannot be called", e)
            if len(e.args) != len(f.params):
                self.fail("G107", f"{name} expects {len(f.params)} arguments", e)
            for arg, (_, typ, _) in zip(e.args, f.params):
                self.same(self.expr(arg, env, unsafe, typ), typ, arg)
            return f.result
        arity = {"print": 1, "len": 1, "range": 1, "fill": 2, "clone": 1, "push": 2,
                 "argi": 1, "clock": 0, "ptr": 1, "load": 1, "store": 2, "offset": 2, "i64": 1, "f64": 1}
        if name not in arity:
            self.fail("G101", f"unknown function {name}", e)
        if len(e.args) != arity[name]:
            self.fail("G107", f"{name} expects {arity[name]} arguments", e)
        if name in {"ptr", "load", "store", "offset"} and not unsafe:
            self.fail("G110", f"{name} requires an unsafe block", e)
        types = [self.expr(x, env, unsafe) for x in e.args]
        if name == "print" and types[0] in SCALARS:
            return "void"
        if name == "clock":
            return "f64"
        if name in {"range", "argi"}:
            self.same(types[0], "i64", e)
            return "[i64]" if name == "range" else "i64"
        if name == "len" and (types[0].startswith("[") or types[0] == "str"):
            return "i64"
        if name == "fill" and types[0] == "i64" and types[1] in SCALARS:
            return f"[{types[1]}]"
        if name == "clone" and types[0].startswith("["):
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
