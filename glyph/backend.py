"""Typed AST -> sequenced C -> Clang/LLVM. C is an internal, inspectable IR."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from .syntax import Diagnostic, Token, Record, Union, Function
from .gui import GUI_SIGNATURES
from .stdlib import STD_SIGNATURES
from .collections import KINDS, collection_type, parts
from .gc_support import collector_object, include_flags
from .abstractions import fn_parts


def ctype(typ):
    if fn_parts(typ):
        return "g_closure"
    if collection_type(typ):
        return "g_collection*"
    if typ.startswith("["):
        return "g_array"
    if typ.startswith("*"):
        return ctype(typ[1:]) + "*"
    return {"i64": "int64_t", "f64": "double", "bool": "bool", "str": "g_str", "void": "void"}.get(typ, "g_record_" + typ)


def function_name(f):
    if f.owner:
        return f"g_method_{len(f.owner)}_{f.owner}_{f.name}"
    return "f_" + f.name


class Emitter:
    def __init__(self):
        self.lines, self.serial, self.level = [], 0, 0
        self.functions = set()
        self.current = None
        self.uses_gui = False
        self.records = {}
        self.closures = []
        self.closure_ids = {}

    def pointer_free(self, typ):
        if typ in {"i64", "f64", "bool"}:
            return True
        record = self.records.get(typ)
        return record is not None and all(self.pointer_free(f.typ) for f in record.fields)

    def write(self, line):
        self.lines.append("    " * self.level + line)

    def fresh(self):
        self.serial += 1
        return f"t{self.serial}"

    def temp(self, typ, value):
        if typ.startswith("[") and self.pointer_free(typ[1:-1]):
            for allocator in ("g_new", "g_clone"):
                if value.startswith(allocator + "("):
                    value = allocator + "_atomic" + value[len(allocator):]
                    break
        if typ == "void":
            self.write(value + ";")
            return ""
        name = self.fresh()
        self.write(f"{ctype(typ)} {name} = {value};")
        return name

    def loc(self, node):
        if node.token.path:
            path = json.dumps(json.dumps(node.token.path, ensure_ascii=True))
            return f"{node.token.line}, (g_file_json = {path}, {node.token.col})"
        return f"{node.token.line}, {node.token.col}"

    def arithmetic(self, op, typ, a, b, node):
        if typ == "i64":
            fn = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod"}[op]
            return f"g_{fn}({a}, {b}, {self.loc(node)})"
        return f"({a} {op} {b})"

    def expr(self, e):
        k, typ, loc = e.kind, e.typ, self.loc(e)
        if k == "name":
            if isinstance(e.target, Function):
                return self.temp(typ, f"(g_closure){{(void (*)(void))g_wrap_{e.value}, NULL}}")
            return self.temp(typ, self.variable(e.value))
        if k == "lambda":
            index = self.closure_ids[id(e)]
            env = "NULL"
            if e.target:
                allocation = self.temp("[str]", f"g_new(1, sizeof(g_env_{index}), {loc})")
                env = allocation + ".data"
                for name, captured_type in e.target:
                    self.write(f"((g_env_{index}*){env})->v_{name} = {self.variable(name)};")
            return self.temp(typ, f"(g_closure){{(void (*)(void))g_lambda_{index}, {env}}}")
        if k == "invoke":
            callee = self.expr(e.args[0])
            args = [self.expr(arg) for arg in e.args[1:]]
            params, result = fn_parts(e.args[0].typ)
            signature = ", ".join(["void *"] + [ctype(t) for t in params])
            values = ", ".join([callee + ".env"] + args)
            return self.temp(typ, f"(({ctype(result)} (*)({signature})){callee}.code)({values})")
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
        if k == "field":
            base = self.expr(e.args[0])
            return self.temp(typ, f"{base}.m_{e.value}")
        if k == "method_call" and collection_type(e.args[0].typ):
            return self.collection_method(e)
        if k == "method_call" and isinstance(e.target, tuple):
            union, index, fields = e.target
            values = [self.expr(arg) for arg in e.args[1:]]
            initializers = [f".m__tag = {index}"] + [f".data.v{index}.m_{f.name} = {value}" for f, value in zip(fields, values)]
            return self.temp(typ, f"({ctype(typ)}){{{', '.join(initializers)}}}")
        if k == "method_call":
            method, args = e.target, []
            if not method.static:
                if method.mut:
                    receiver = self.lvalue(e.args[0])
                    ref = self.fresh()
                    self.write(f"{ctype(method.owner)} *{ref} = &({receiver});")
                    args.append(ref)
                else:
                    args.append(self.expr(e.args[0]))
            args += [self.expr(arg) for arg in e.args[1:]]
            return self.temp(typ, f"{function_name(method)}({', '.join(args)})")
        if k == "fold":
            array = self.expr(e.args[0])
            result = self.expr(e.args[1])
            if typ == "i64" and e.value == "+":
                return self.temp(typ, f"g_sum_i64({array}, {result}, {loc})")
            i = self.fresh()
            self.write(f"for (int64_t {i}=0; {i}<{array}.len; ++{i}) {{")
            self.level += 1
            item = f"(({ctype(typ)}*){array}.data)[{i}]"
            self.write(f"{result} = {self.arithmetic(e.value, typ, result, item, e)};")
            self.level -= 1
            self.write("}")
            return result
        if k == "reduce":
            return self.reduction(e)
        if k == "call":
            return self.call(e)
        raise AssertionError(k)

    def reduction(self, e):
        name, bindings, _ = e.value
        arrays = [self.expr(source) for source in e.args[1:]]
        for array in arrays[1:]:
            self.write(f"if ({array}.len != {arrays[0]}.len) "
                       f'g_fail("R007", "zip arrays must have equal lengths", {self.loc(e)});')
        result = self.temp(e.typ, "0.0" if e.typ == "f64" else "0")
        i = self.fresh()
        self.write(f"for (int64_t {i}=0; {i}<{arrays[0]}.len; ++{i}) {{")
        self.level += 1
        for binding, source, array in zip(bindings, e.args[1:], arrays):
            ct = ctype(source.typ[1:-1])
            self.write(f"{ct} v_{binding.text} = (({ct}*){array}.data)[{i}];")
        item = self.expr(e.args[0])
        if name == "count":
            # At most one increment per array element; the length fits i64.
            self.write(f"if ({item}) ++{result};")
        else:
            self.write(f"{result} = {self.arithmetic('+', e.typ, result, item, e)};")
        self.level -= 1
        self.write("}")
        return result

    def variable(self, name):
        if name == "self" and self.current and self.current.mut:
            return "(*v_self)"
        return "v_" + name

    def lvalue(self, e):
        if e.kind == "name":
            return self.variable(e.value)
        if e.kind == "field":
            return f"({self.lvalue(e.args[0])}).m_{e.value}"
        a, i = [self.expr(x) for x in e.args]
        checked = self.temp("i64", f"g_index({a}, {i}, {self.loc(e)})")
        return f"(({ctype(e.typ)}*){a}.data)[{checked}]"

    def collection_method(self, e):
        args = [self.expr(x) for x in e.args]
        a, name, loc = args[0], e.value, self.loc(e)
        kind, _ = parts(e.args[0].typ)
        key = '&' + args[1] if len(args) > 1 else 'NULL'
        if name == 'clear':
            value = f'g_coll_clear({a})'
        elif name in {'to_array', 'keys', 'values'}:
            keys = int(kind == 'set' or name == 'keys')
            value = f'g_coll_snapshot({a}, {keys}, {loc})'
        elif name == 'append':
            value = f'g_coll_append({a}, {key}, {loc})'
        elif name == 'set':
            value = f'g_coll_set({a}, {args[1]}, &{args[2]}, {loc})'
        elif name in {'pop', 'remove'} and kind == 'list':
            index = f'{a}->len - 1' if name == 'pop' else args[1]
            value = f'*({ctype(e.typ)}*)g_coll_take({a}, {index}, {loc})'
        elif name in {'get', 'get_or'}:
            fallback = '&' + args[2] if name == 'get_or' else 'NULL'
            value = f'*({ctype(e.typ)}*)g_coll_get({a}, {key}, {fallback}, {loc})'
        elif name in {'put', 'add'}:
            item = '&' + args[2] if name == 'put' else 'NULL'
            value = f'g_coll_put({a}, {key}, {item}, {loc})'
        elif name in {'contains', 'remove'}:
            value = f'g_coll_{name}({a}, {key})'
        else:
            raise AssertionError(name)
        return self.temp(e.typ, value)

    def call(self, e):
        args = [self.expr(x) for x in e.args]
        name, typ, loc = e.value, e.typ, self.loc(e)
        a = args[0] if args else ""
        if name in KINDS:
            kind, items = parts(typ)
            key, value_type = items[0], items[-1]
            key_kind = {'i64': 0, 'bool': 1, 'str': 2}.get(key, 0)
            keys = args[0] if kind != 'list' else '(g_array){0}'
            values = args[-1] if kind != 'set' else '(g_array){0}'
            return self.temp(typ, f"g_coll_new({dict(list=0, map=1, set=2)[kind]}, {key_kind}, sizeof({ctype(key)}), sizeof({ctype(value_type)}), {int(self.pointer_free(key))}, {int(self.pointer_free(value_type))}, {keys}, {values}, {loc})")
        if name in {'len', 'clone'} and collection_type(e.args[0].typ):
            return self.temp(typ, f'{a}->len' if name == 'len' else f'g_coll_clone({a}, {loc})')
        if isinstance(e.target, Record):
            return self.temp(typ, f"({ctype(typ)}){{{', '.join(args)}}}")
        if name == "print":
            value = f"g_print_{e.args[0].typ}({a})"
        elif name in GUI_SIGNATURES:
            self.uses_gui = True
            value = f"g_{name}({', '.join([*args, loc])})"
        elif name in STD_SIGNATURES:
            value = f"g_std_{name}({', '.join([*args, loc])})"
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
            n = a if name == "fill" else self.temp("i64", f"g_add({a}.len, 1, {loc})")
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
        elif name in {"sum", "count"} and name not in self.functions:
            if name == "sum" and typ == "i64":
                return self.temp(typ, f"g_sum_i64({a}, 0, {loc})")
            result = self.temp(typ, "0.0" if typ == "f64" else "0")
            i = self.fresh()
            self.write(f"for (int64_t {i}=0; {i}<{a}.len; ++{i}) {{")
            self.level += 1
            ct = ctype(e.args[0].typ[1:-1])
            item = f"(({ct}*){a}.data)[{i}]"
            self.write(f"if ({item}) ++{result};" if name == "count" else f"{result} += {item};")
            self.level -= 1
            self.write("}")
            return result
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
                source_type = s.args[0].typ
                if collection_type(source_type):
                    kind, items = parts(source_type)
                    source_type = f'[{items[0]}]'
                    array = self.temp(source_type, f'g_coll_snapshot({array}, {int(kind != "list")}, {self.loc(s)})')
                i = self.fresh()
                self.write(f"for (int64_t {i}=0; {i}<{array}.len; ++{i}) {{")
                self.level += 1
                ct = ctype(source_type[1:-1])
                self.write(f"{ct} v_{s.value} = (({ct}*){array}.data)[{i}];")
                self.block(s.body)
                self.level -= 1
                self.write("}")
            elif s.kind == "match":
                value = self.expr(s.args[0])
                self.write(f"switch ({value}.m__tag) {{")
                for arm in s.body:
                    index, fields = arm.target
                    self.write(f"case {index}: {{")
                    self.level += 1
                    for name, field in zip(arm.value[1], fields):
                        self.write(f"{ctype(field.typ)} v_{name} = {value}.data.v{index}.m_{field.name};")
                    self.block(arm.body)
                    self.write("break;")
                    self.level -= 1
                    self.write("}")
                self.write("default: abort();")
                self.write("}")
            elif s.kind == "unsafe":
                self.write("{")
                self.level += 1
                self.block(s.body)
                self.level -= 1
                self.write("}")

    def signature(self, f):
        params = [f"{ctype(t)} v_{n}" for n, t, _ in f.params]
        if f.owner and not f.static:
            params.insert(0, f"{ctype(f.owner)}{' *' if f.mut else ' '}v_self")
        return f"static {ctype(f.result)} {function_name(f)}({', '.join(params) or 'void'})"

    def emit(self, declarations, filename="<source>"):
        functions = [f for f in declarations if isinstance(f, Function)]
        records = {r.name: r for r in declarations if isinstance(r, Record)}
        self.records = records
        self.functions = {f.name for f in functions}
        functions += [m for r in records.values() for m in r.methods]
        file_json = json.dumps(str(filename), ensure_ascii=True).encode("utf-8")
        file_literal = '"' + ''.join(f"\\{b:03o}" for b in file_json) + '"'
        self.write(f"#define G_FILE_JSON {file_literal}")
        self.write(Path(__file__).with_name("runtime.h").read_text())
        self.write(Path(__file__).with_name("std_runtime.h").read_text())
        self.write(Path(__file__).with_name("io_runtime.h").read_text())
        self.write(Path(__file__).with_name("json_runtime.h").read_text())
        self.write(Path(__file__).with_name("collections_runtime.h").read_text())
        self.write("typedef struct { void (*code)(void); void *env; } g_closure;")
        for name in records:
            self.write(f"typedef struct {ctype(name)} {ctype(name)};")
        defined = set()
        def define_record(name):
            if name in defined:
                return
            record = records[name]
            for field in record.fields:
                if field.typ in records:
                    define_record(field.typ)
            self.write(f"struct {ctype(name)} {{")
            if isinstance(record, Union):
                self.write("    int64_t m__tag;")
                self.write("    union {")
                for i, (_, fields, _) in enumerate(record.variants):
                    self.write("        struct {")
                    for field in fields:
                        self.write(f"            {ctype(field.typ)} m_{field.name};")
                    if not fields:
                        self.write("            char empty;")
                    self.write(f"        }} v{i};")
                self.write("    } data;")
            else:
                for field in record.fields:
                    self.write(f"    {ctype(field.typ)} m_{field.name};")
            self.write("};")
            defined.add(name)
        for name in records:
            define_record(name)
        for f in functions:
            self.write(self.signature(f) + ";")
        # Collect before emission so nested/escaping lambdas have prototypes.
        def scan_expr(e):
            if e.kind == "lambda" and id(e) not in self.closure_ids:
                self.closure_ids[id(e)] = len(self.closures)
                self.closures.append(e)
            for arg in e.args:
                scan_expr(arg)
        def scan_block(body):
            for stmt in body:
                for arg in stmt.args:
                    scan_expr(arg)
                scan_block(stmt.body)
                scan_block(stmt.other)
        for f in functions:
            scan_block(f.body)
        for f in functions:
            if f.owner or f.name == "main":
                continue
            params = ["void *env"] + [f"{ctype(t)} v_{n}" for n, t, _ in f.params]
            self.write(f"static {ctype(f.result)} g_wrap_{f.name}({', '.join(params)}) {{")
            call = f"{function_name(f)}({', '.join('v_' + n for n, _, _ in f.params)})"
            self.write(("    " if f.result == "void" else "    return ") + call + ";")
            self.write("}")
        for i, e in enumerate(self.closures):
            params, result = e.value
            if e.target:
                self.write(f"typedef struct {{")
                for name, typ in e.target:
                    self.write(f"    {ctype(typ)} v_{name};")
                self.write(f"}} g_env_{i};")
            signature = ', '.join(["void *env"] + [f"{ctype(t)} v_{n}" for n, t, _ in params])
            self.write(f"static {ctype(result)} g_lambda_{i}({signature});")
        for i, e in enumerate(self.closures):
            params, result = e.value
            signature = ', '.join(["void *env"] + [f"{ctype(t)} v_{n}" for n, t, _ in params])
            self.write(f"static {ctype(result)} g_lambda_{i}({signature}) {{")
            self.level += 1
            for name, typ in e.target:
                self.write(f"{ctype(typ)} v_{name} = ((g_env_{i}*)env)->v_{name};")
            value = self.expr(e.args[0])
            self.write("return " + value + ";" if result != "void" else "return;")
            self.level -= 1
            self.write("}")
        for f in functions:
            self.current = f
            self.write(self.signature(f) + " {")
            self.level += 1
            self.block(f.body)
            self.level -= 1
            self.write("}")
        self.current = None
        main = next(f for f in functions if f.name == "main" and not f.owner)
        self.write("int main(int argc, char **argv) {")
        self.write("    g_argc=argc; g_argv=argv; g_gc_init();")
        if main.result == "void":
            self.write("    f_main(); return 0;")
        else:
            self.write("    return (int)((uint64_t)f_main() & 255);")
        self.write("}")
        if self.uses_gui:
            # Keep generated C inspectable and independent of include paths.
            support = "#define GLYPH_GUI 1\n"
            support += Path(__file__).with_name("gui.h").read_text() + "\n"
            support += Path(__file__).with_name("gui_runtime.h").read_text() + "\n"
            self.lines.insert(2, support)
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
    source_text = Path(source).read_text(encoding="utf-8")
    gui = "#define GLYPH_GUI 1\n" in source_text
    if gui:
        if sys.platform != "darwin":
            raise Diagnostic("G203", "the native GUI backend currently requires macOS; console programs remain portable", Token("", 1, 1, 1))
        # AppKit's Objective-C backend uses Apple's SDK/toolchain. Ordinary
        # programs continue to use the portable Zig/Clang path above.
        if not shutil.which("xcrun"):
            raise Diagnostic("G201", "install Apple's Command Line Tools for GUI builds", Token("", 1, 1, 1))
        cc = ["xcrun", "clang"]
    else:
        cc = compiler()
    command = cc + ["-x", "c", str(Path(source).resolve()), "-std=c11", f"-O{optimization}", "-fno-fast-math", "-ffp-contract=off", "-o", str(output)]
    if "#define GLYPH_GC 1\n" in source_text:
        command += include_flags() + ["-x", "none", str(collector_object(cc, cache, env))]
        if sys.platform.startswith("linux"):
            command += ["-ldl"]
    if gui:
        command += ["-x", "objective-c", str(Path(__file__).with_name("gui_macos.m")),
                    "-fobjc-arc", "-D_DARWIN_C_SOURCE", "-framework", "AppKit"]
    if os.name != "nt":
        command += ["-D_POSIX_C_SOURCE=200809L", "-lm"]
    proc = subprocess.run(command, capture_output=True, text=True, env=env)
    if proc.returncode:
        raise Diagnostic("G202", "native backend failed: " + proc.stderr[-4000:], Token("", 1, 1, 1))
    return command
