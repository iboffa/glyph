"""Canonical AST printer. Comments are retained as standalone comments."""
import json
import math
from .syntax import parse, PREC


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
    if e.kind == "call":
        return e.value + "(" + ", ".join(expression(a) for a in e.args) + ")"
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
                text = f"{s.value[0]}:{s.value[1]} = {expression(s.args[0])}"
            elif s.kind == "set":
                text = f"{expression(s.args[0])} {s.value} {expression(s.args[1])}"
            elif s.kind == "ret":
                text = "ret" + (" " + expression(s.args[0]) if s.args else "")
            elif s.kind == "expr":
                text = expression(s.args[0])
            elif s.kind in {"if", "while"}:
                text = s.kind + " " + expression(s.args[0])
            elif s.kind == "for":
                text = f"for {s.value}:{expression(s.args[0])}"
            else:
                text = "unsafe"
            out.append(prefix + text)
            if s.body:
                block(s.body, depth + 1)
            if s.other:
                out.append(prefix + "else")
                block(s.other, depth + 1)

    for f in functions:
        if out:
            out.append("")
        drain(f.token.line, 0)
        params = ", ".join(f"{n}:{t}" for n, t, _ in f.params)
        header = f.name + (" " + params if params else "") + ">" + f.result
        # Preserve comments in a multiline function rather than moving them into its header.
        compact = len(f.body) == 1 and f.body[0].kind == "ret" and f.body[0].args and not any(f.token.line < n <= f.body[0].token.line for n, _ in comments)
        if compact:
            out.append(header + " = " + expression(f.body[0].args[0]))
        else:
            out.append(header)
            block(f.body, 1)
    drain(float("inf"), 0)
    return "\n".join(out) + "\n"
