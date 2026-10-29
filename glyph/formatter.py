"""Canonical AST printer. Comments are retained as standalone comments."""
import json
import math
from .syntax import parse, PREC, Record, Union, Interface, Field, Import


def expression(e, minimum=0):
    if e.kind in {"name", "i64", "f64", "bool"}:
        if e.kind == "i64":
            return str(int(e.value))
        if e.kind == "f64":
            return repr(float(e.value)) if math.isfinite(float(e.value)) else e.value
        return str(e.value)
    if e.kind == "str":
        return json.dumps(e.value, ensure_ascii=False)
    if e.kind == "array":
        return "[" + ", ".join(expression(a) for a in e.args) + "]"
    if e.kind == "specialize":
        return e.value[0] + "[" + ",".join(e.value[1]) + "]"
    if e.kind == "lambda":
        params, result = e.value
        text = "fn(" + ", ".join(n + ":" + t for n, t, _ in params) + ")>" + result + " = " + expression(e.args[0])
        return "(" + text + ")" if minimum else text
    if e.kind == "invoke":
        return expression(e.args[0], 8) + "(" + ", ".join(expression(a) for a in e.args[1:]) + ")"
    if e.kind == "call":
        return e.value + "(" + ", ".join(expression(a) for a in e.args) + ")"
    if e.kind == "field":
        return expression(e.args[0], 8) + "." + e.value
    if e.kind == "method_call":
        return expression(e.args[0], 8) + "." + e.value + "(" + ", ".join(expression(a) for a in e.args[1:]) + ")"
    if e.kind == "reduce":
        name, bindings, zipped = e.value
        sources = ", ".join(expression(a) for a in e.args[1:])
        iterable = f"zip({sources})" if zipped else sources
        names = ", ".join(t.text for t in bindings)
        return f"{name}({expression(e.args[0])} for {names} in {iterable})"
    if e.kind == "index":
        return expression(e.args[0], 8) + "[" + expression(e.args[1]) + "]"
    if e.kind == "unary":
        result = ("not " if e.value == "not" else "-") + expression(e.args[0], 7)
        return "(" + result + ")" if minimum > 7 else result
    if e.kind == "fold":
        result = f"fold {expression(e.args[0], 7)} {expression(e.args[1], 7)} {e.value}"
        return "(" + result + ")" if minimum else result
    if e.kind == "binary":
        p = PREC[e.value]
        result = f"{expression(e.args[0], p)} {e.value} {expression(e.args[1], p + 1)}"
        return "(" + result + ")" if p < minimum else result
    raise AssertionError(e.kind)


def format_source(source):
    functions = parse(source)
    comments = []
    for number, line in enumerate(source.splitlines(), 1):
        quoted, escaped = False, False
        for i, ch in enumerate(line):
            if escaped:
                escaped = False
            elif ch == "\\" and quoted:
                escaped = True
            elif ch == '"':
                quoted = not quoted
            elif ch == "#" and not quoted:
                comments.append((number, "# " + line[i + 1:].strip()))
                break
    out = []

    def drain(line, depth):
        while comments and comments[0][0] <= line:
            out.append("  " * depth + comments.pop(0)[1])

    def block(body, depth):
        for s in body:
            drain(s.token.line, depth)
            prefix = "  " * depth
            if s.kind == "var":
                declaration = f"{s.value[0]}:{s.value[1]} =" if s.value[1] else f"{s.value[0]} :="
                text = f"{declaration} {expression(s.args[0])}"
            elif s.kind == "set":
                text = f"{expression(s.args[0])} {s.value} {expression(s.args[1])}"
            elif s.kind == "ret":
                text = "ret" + (" " + expression(s.args[0]) if s.args else "")
            elif s.kind == "expr":
                text = expression(s.args[0])
            elif s.kind == "match":
                text = "match " + expression(s.args[0])
            elif s.kind == "case":
                text = "case " + s.value[0] + "(" + ", ".join(s.value[1]) + ")"
            elif s.kind in {"if", "while"}:
                text = s.kind + " " + expression(s.args[0])
            elif s.kind == "borrow":
                text = "borrow " + s.value + " = " + expression(s.args[0])
            elif s.kind == "for":
                text = f"for {s.value}:{expression(s.args[0])}"
            else:
                text = s.kind
            out.append(prefix + text)
            if s.body:
                block(s.body, depth + 1)
            if s.other:
                out.append(prefix + "else")
                block(s.other, depth + 1)

    def type_params(d):
        return "[" + ", ".join(n + (":" + c if c else "") for n, c, _ in d.type_params) + "]" if d.type_params else ""

    def function(f, depth):
        drain(f.token.line, depth)
        params = ", ".join(f"{n}:{t}" for n, t, _ in f.params)
        modifiers = ("@noalloc " if f.noalloc else "") + ("private " if f.private else "") + ("mut " if f.mut else "static " if f.static else "")
        header = "  " * depth + modifiers + f.name + type_params(f) + (" " + params if params else "") + (">" + f.result if f.result else "")
        # Preserve comments in a multiline function rather than moving them into its header.
        compact = len(f.body) == 1 and f.body[0].kind == "ret" and f.body[0].args and not any(f.token.line < n <= f.body[0].token.line for n, _ in comments)
        if compact:
            out.append(header + " = " + expression(f.body[0].args[0]))
        else:
            out.append(header)
            block(f.body, depth + 1)

    for declaration in functions:
        if out:
            out.append("")
        if isinstance(declaration, Import):
            drain(declaration.token.line, 0)
            out.append("import " + ", ".join(t.text for t in declaration.names) + " from " + json.dumps(declaration.path, ensure_ascii=False))
        elif isinstance(declaration, Record):
            drain(declaration.token.line, 0)
            kind = "union" if isinstance(declaration, Union) else "interface" if isinstance(declaration, Interface) else "type"
            out.append(kind + " " + declaration.name + type_params(declaration))
            if isinstance(declaration, Union):
                for name, fields, token in declaration.variants:
                    drain(token.line, 1)
                    out.append("  " + name + (" " + ", ".join(f.name + ":" + f.typ for f in fields) if fields else ""))
                continue
            if isinstance(declaration, Interface):
                for m in declaration.methods:
                    drain(m.token.line, 1)
                    params = ", ".join(n + ":" + t for n, t, _ in m.params)
                    out.append("  " + ("mut " if m.mut else "") + m.name + (" " + params if params else "") + ">" + m.result)
                continue
            for member in sorted([*declaration.fields, *declaration.methods], key=lambda m: m.token.line):
                if isinstance(member, Field):
                    drain(member.token.line, 1)
                    out.append("  " + ("private " if member.private else "") + f"{member.name}:{member.typ}")
                else:
                    function(member, 1)
        else:
            function(declaration, 0)
    drain(float("inf"), 0)
    return "\n".join(out) + "\n"
