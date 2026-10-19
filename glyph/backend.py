"""Typed AST -> sequenced C -> Clang/LLVM. C is an internal, inspectable IR."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
from .syntax import Diagnostic, Token


def ctype(typ):
    if typ.startswith("["):
        return "g_array"
    if typ.startswith("*"):
        return ctype(typ[1:]) + "*"
    return {"i64": "int64_t", "f64": "double", "bool": "bool", "str": "g_str", "void": "void"}[typ]


class Emitter:
    def __init__(self):
        self.lines, self.serial, self.level = [], 0, 0

    def write(self, line):
        self.lines.append("    " * self.level + line)

    def fresh(self):
        self.serial += 1
        return f"t{self.serial}"

    def temp(self, typ, value):
        if typ == "void":
            self.write(value + ";")
            return ""
        name = self.fresh()
        self.write(f"{ctype(typ)} {name} = {value};")
        return name

    def loc(self, node):
        return f"{node.token.line}, {node.token.col}"

    def arithmetic(self, op, typ, a, b, node):
        if typ == "i64":
            fn = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod"}[op]
            return f"g_{fn}({a}, {b}, {self.loc(node)})"
        return f"({a} {op} {b})"

    def expr(self, e):
        k, typ, loc = e.kind, e.typ, self.loc(e)
        if k == "name":
            return self.temp(typ, "v_" + e.value)
        if k == "str":
            raw = e.value.encode("utf-8")
            literal = '"' + ''.join(f"\\{b:03o}" for b in raw) + '"'
            return self.temp(typ, f"(g_str){{{literal}, {len(raw)}}}")
        if k in {"i64", "f64", "bool"}:
            value = str(e.value)
            if k == "i64":
                value = "INT64_MIN" if value == "-9223372036854775808" else f"INT64_C({int(value)})"
            elif k == "f64":
                value = repr(float(value))
            return self.temp(typ, value)
        if k == "unary":
            a = self.expr(e.args[0])
            value = f"!{a}" if e.value == "not" else self.arithmetic("-", typ, "0", a, e)
            return self.temp(typ, value)
        if k == "binary":
            a = self.expr(e.args[0])
            op = e.value
            if op in {"and", "or"}:
                result = self.temp("bool", a)
                self.write(f"if ({'' if op == 'and' else '!'}{result}) {{")
                self.level += 1
                b = self.expr(e.args[1])
                self.write(f"{result} = {b};")
                self.level -= 1
                self.write("}")
                return result
            b = self.expr(e.args[1])
            if op in {"+", "-", "*", "/", "%"}:
                value = self.arithmetic(op, typ, a, b, e)
            elif e.args[0].typ == "str":
                value = f"{'!' if op == '!=' else ''}g_eq({a}, {b})"
            else:
                value = f"({a} {op} {b})"
            return self.temp(typ, value)
        if k == "array":
            values = [self.expr(a) for a in e.args]
            ct = ctype(typ[1:-1])
            result = self.temp(typ, f"g_new({len(values)}, sizeof({ct}), {loc})")
            for i, value in enumerate(values):
                self.write(f"(({ct}*){result}.data)[{i}] = {value};")
            return result
        if k == "index":
            return self.temp(typ, self.lvalue(e))
        if k == "fold":
            array = self.expr(e.args[0])
            result = self.expr(e.args[1])
            i = self.fresh()
            self.write(f"for (int64_t {i}=0; {i}<{array}.len; ++{i}) {{")
            self.level += 1
            item = f"(({ctype(typ)}*){array}.data)[{i}]"
            self.write(f"{result} = {self.arithmetic(e.value, typ, result, item, e)};")
            self.level -= 1
            self.write("}")
            return result
        if k == "call":
            return self.call(e)
        raise AssertionError(k)

    def lvalue(self, e):
        if e.kind == "name":
            return "v_" + e.value
        a, i = [self.expr(x) for x in e.args]
        checked = self.temp("i64", f"g_index({a}, {i}, {self.loc(e)})")
        return f"(({ctype(e.typ)}*){a}.data)[{checked}]"

    def call(self, e):
        args = [self.expr(x) for x in e.args]
        name, typ, loc = e.value, e.typ, self.loc(e)
        a = args[0] if args else ""
        if name == "print":
            value = f"g_print_{e.args[0].typ}({a})"
        elif name == "len":
            value = f"{a}.len"
        elif name in {"range", "argi"}:
            value = f"g_{name}({a}, {loc})"
        elif name == "clock":
            value = "g_clock()"
        elif name == "clone":
            value = f"g_clone({a}, sizeof({ctype(typ[1:-1])}), {loc})"
        elif name in {"fill", "push"}:
            ct = ctype(typ[1:-1])
            n = a if name == "fill" else f"g_add({a}.len, 1, {loc})"
            result = self.temp(typ, f"g_new({n}, sizeof({ct}), {loc})")
            if name == "push":
                self.write(f"memcpy({result}.data, {a}.data, (size_t){a}.len*sizeof({ct}));")
                self.write(f"(({ct}*){result}.data)[{a}.len] = {args[1]};")
            else:
                i = self.fresh()
                self.write(f"for (int64_t {i}=0; {i}<{a}; ++{i}) (({ct}*){result}.data)[{i}] = {args[1]};")
            return result
        elif name == "ptr":
            value = f"({ctype(typ)}){a}.data"
        elif name == "load":
            value = f"*{a}"
        elif name == "store":
            self.write(f"*{a} = {args[1]};")
            return ""
        elif name == "offset":
            value = f"({a} + {args[1]})"
        elif name in {"i64", "f64"}:
            value = f"g_to_i64({a}, {loc})" if name == "i64" and e.args[0].typ == "f64" else f"({ctype(typ)}){a}"
        else:
            value = f"f_{name}({', '.join(args)})"
        return self.temp(typ, value)

    def block(self, body):
        for s in body:
            if s.kind == "var":
                value = self.expr(s.args[0])
                name, typ = s.value
                self.write(f"{ctype(typ)} v_{name} = {value};")
            elif s.kind == "set":
                left = self.lvalue(s.args[0])
                old = self.temp(s.args[0].typ, left) if s.value != "=" else None
                right = self.expr(s.args[1])
                value = right if old is None else self.arithmetic(s.value[0], s.args[0].typ, old, right, s)
                self.write(f"{left} = {value};")
            elif s.kind == "ret":
                value = self.expr(s.args[0]) if s.args else ""
                self.write(f"return {value};")
            elif s.kind == "expr":
                self.expr(s.args[0])
            elif s.kind == "if":
                cond = self.expr(s.args[0])
                self.write(f"if ({cond}) {{")
                self.level += 1
                self.block(s.body)
                self.level -= 1
                if s.other:
                    self.write("} else {")
                    self.level += 1
                    self.block(s.other)
                    self.level -= 1
                self.write("}")
            elif s.kind == "while":
                self.write("while (true) {")
                self.level += 1
                cond = self.expr(s.args[0])
                self.write(f"if (!{cond}) break;")
                self.block(s.body)
                self.level -= 1
                self.write("}")
            elif s.kind == "for":
                array = self.expr(s.args[0])
                i = self.fresh()
                self.write(f"for (int64_t {i}=0; {i}<{array}.len; ++{i}) {{")
                self.level += 1
                ct = ctype(s.args[0].typ[1:-1])
                self.write(f"{ct} v_{s.value} = (({ct}*){array}.data)[{i}];")
                self.block(s.body)
                self.level -= 1
                self.write("}")
            elif s.kind == "unsafe":
                self.write("{")
                self.level += 1
                self.block(s.body)
                self.level -= 1
                self.write("}")

    def emit(self, functions, filename="<source>"):
        file_json = json.dumps(str(filename), ensure_ascii=True).encode("utf-8")
        file_literal = '"' + ''.join(f"\\{b:03o}" for b in file_json) + '"'
        self.write(f"#define G_FILE_JSON {file_literal}")
        self.write(Path(__file__).with_name("runtime.h").read_text())
        for f in functions:
            params = ", ".join(f"{ctype(t)} v_{n}" for n, t, _ in f.params) or "void"
            self.write(f"static {ctype(f.result)} f_{f.name}({params});")
        for f in functions:
            params = ", ".join(f"{ctype(t)} v_{n}" for n, t, _ in f.params) or "void"
            self.write(f"static {ctype(f.result)} f_{f.name}({params}) {{")
            self.level += 1
            self.block(f.body)
            self.level -= 1
            self.write("}")
        main = next(f for f in functions if f.name == "main")
        self.write("int main(int argc, char **argv) {")
        self.write("    g_argc=argc; g_argv=argv; atexit(g_cleanup);")
        if main.result == "void":
            self.write("    f_main(); return 0;")
        else:
            self.write("    return (int)((uint64_t)f_main() & 255);")
        self.write("}")
        return "\n".join(self.lines) + "\n"


def compiler():
    spec = importlib.util.find_spec("ziglang")
    if spec:
        executable = Path(spec.origin).parent / ("zig.exe" if os.name == "nt" else "zig")
        return [str(executable), "cc"]
    if shutil.which("clang"):
        return [shutil.which("clang")]
    raise Diagnostic("G201", "install ziglang==0.14.1 or put clang on PATH", Token("", 1, 1, 1))


def compile_c(source, output, optimization="2"):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    cache = Path(os.environ.get("GLYPH_CACHE_DIR", str(Path.cwd() / "build" / ".glyph-cache"))).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache), TEMP=str(cache), TMP=str(cache))
    command = compiler() + ["-x", "c", str(Path(source).resolve()), "-std=c11", f"-O{optimization}", "-fno-fast-math", "-ffp-contract=off", "-o", str(output)]
    if os.name != "nt":
        command += ["-D_POSIX_C_SOURCE=200809L", "-lm"]
    proc = subprocess.run(command, capture_output=True, text=True, env=env)
    if proc.returncode:
        raise Diagnostic("G202", "native backend failed: " + proc.stderr[-4000:], Token("", 1, 1, 1))
    return command
