"""Indentation lexer and recursive-descent/Pratt parser. No host-language eval."""
from dataclasses import dataclass, field
import json
import re


@dataclass
class Token:
    text: str
    line: int
    col: int
    end: int


class Diagnostic(Exception):
    def __init__(self, code, message, token):
        super().__init__(message)
        self.code, self.message, self.token = code, message, token

    def record(self, path):
        t = self.token
        return {"code": self.code, "severity": "error", "message": self.message,
                "file": str(path), "span": {"start": {"line": t.line, "column": t.col},
                "end": {"line": t.line, "column": t.end}}}


@dataclass
class Expr:
    kind: str
    token: Token
    value: object = None
    args: list = field(default_factory=list)
    typ: str = ""


@dataclass
class Stmt:
    kind: str
    token: Token
    value: object = None
    args: list = field(default_factory=list)
    body: list = field(default_factory=list)
    other: list = field(default_factory=list)


@dataclass
class Function:
    name: str
    token: Token
    params: list
    result: str
    body: list
    short: bool = False


LEX = re.compile(r'"(?:[^"\\\r\n]|\\.)*"|[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|[A-Za-z_][A-Za-z_0-9]*|==|!=|<=|>=|\+=|-=|\*=|/=|%=|[+*/%<>=!,:()\[\]>\-]')
IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
RESERVED = {"if", "else", "while", "for", "ret", "unsafe", "true", "false", "and", "or", "not", "fold"}
PREC = {"or": 1, "and": 2, "==": 3, "!=": 3, "<": 4, "<=": 4, ">": 4, ">=": 4,
        "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}


def lex(source):
    out, levels = [], [0]
    lines = source.splitlines()
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" in line[:len(line) - len(line.lstrip())]:
            raise Diagnostic("G001", "indent with spaces, not tabs", Token("", number, 1, 2))
        width = len(line) - len(line.lstrip(" "))
        if width > levels[-1]:
            levels.append(width)
            out.append(Token("INDENT", number, 1, width + 1))
        while width < levels[-1]:
            levels.pop()
            out.append(Token("DEDENT", number, 1, width + 1))
        if width != levels[-1]:
            raise Diagnostic("G001", "indentation does not match an outer block", Token("", number, 1, width + 1))
        pos = width
        while pos < len(line):
            if line[pos] == "#":
                break
            if line[pos] == " ":
                pos += 1
                continue
            match = LEX.match(line, pos)
            if not match:
                raise Diagnostic("G001", "unexpected character or unterminated string", Token(line[pos], number, pos + 1, pos + 2))
            out.append(Token(match[0], number, pos + 1, match.end() + 1))
            pos = match.end()
        out.append(Token("NEWLINE", number, len(line) + 1, len(line) + 1))
    end = len(lines) + 1
    out.extend(Token("DEDENT", end, 1, 1) for _ in levels[1:])
    out.append(Token("EOF", end, 1, 1))
    return out


class Parser:
    def __init__(self, source):
        self.tokens, self.i = lex(source), 0

    @property
    def t(self):
        return self.tokens[self.i]

    def pop(self):
        token = self.t
        self.i += 1
        return token

    def accept(self, text):
        if self.t.text == text:
            return self.pop()
        return None

    def need(self, text):
        if self.t.text != text:
            raise Diagnostic("G002", f"expected {text}, found {self.t.text}", self.t)
        return self.pop()

    def name(self):
        if not IDENT.fullmatch(self.t.text) or self.t.text in RESERVED or self.t.text in {"EOF", "NEWLINE", "INDENT", "DEDENT"}:
            raise Diagnostic("G002", "expected an identifier", self.t)
        return self.pop()

    def type(self):
        if self.accept("["):
            item = self.name()
            self.need("]")
            if item.text not in {"i64", "f64", "bool", "str"}:
                raise Diagnostic("G003", "array element must be i64, f64, bool or str", item)
            return f"[{item.text}]"
        if self.accept("*"):
            item = self.name()
            if item.text not in {"i64", "f64", "bool"}:
                raise Diagnostic("G003", "pointer element must be i64, f64 or bool", item)
            return "*" + item.text
        token = self.name()
        if token.text not in {"i64", "f64", "bool", "str", "void"}:
            raise Diagnostic("G003", f"unknown type {token.text}", token)
        return token.text

    def parse(self):
        result = []
        while self.t.text != "EOF":
            name = self.name()
            params = []
            while self.t.text != ">":
                arg = self.name()
                self.need(":")
                params.append((arg.text, self.type(), arg))
                if not self.accept(","):
                    break
            self.need(">")
            typ = self.type()
            short = bool(self.accept("="))
            if short:
                expr = self.expr()
                self.need("NEWLINE")
                body = [Stmt("ret", expr.token, args=[expr])]
            else:
                body = self.block()
            result.append(Function(name.text, name, params, typ, body, short))
        return result

    def block(self):
        self.need("NEWLINE")
        self.need("INDENT")
        body = []
        while self.t.text not in {"DEDENT", "EOF"}:
            body.append(self.statement())
        self.need("DEDENT")
        return body

    def statement(self):
        t = self.t
        if self.accept("if"):
            expr = self.expr()
            body = self.block()
            other = self.block() if self.accept("else") else []
            return Stmt("if", t, args=[expr], body=body, other=other)
        if self.accept("while"):
            expr = self.expr()
            return Stmt("while", t, args=[expr], body=self.block())
        if self.accept("for"):
            name = self.name().text
            self.need(":")
            expr = self.expr()
            return Stmt("for", t, value=name, args=[expr], body=self.block())
        if self.accept("unsafe"):
            return Stmt("unsafe", t, body=self.block())
        if self.accept("ret"):
            args = [] if self.t.text == "NEWLINE" else [self.expr()]
            stmt = Stmt("ret", t, args=args)
        elif IDENT.fullmatch(t.text) and self.tokens[self.i + 1].text == ":":
            name = self.name().text
            self.need(":")
            typ = self.type()
            self.need("=")
            stmt = Stmt("var", t, (name, typ), [self.expr()])
        else:
            left = self.expr()
            if self.t.text in {"=", "+=", "-=", "*=", "/=", "%="}:
                op = self.pop().text
                stmt = Stmt("set", t, op, [left, self.expr()])
            else:
                stmt = Stmt("expr", t, args=[left])
        self.need("NEWLINE")
        return stmt

    def expr(self, minimum=0):
        t = self.pop()
        if t.text in {"-", "not"}:
            left = Expr("unary", t, t.text, [self.expr(7)])
        elif t.text == "fold":
            array = self.expr(7)
            initial = self.expr(7)
            op = self.pop()
            if op.text not in {"+", "*"}:
                raise Diagnostic("G002", "fold reducer must be + or *", op)
            left = Expr("fold", t, op.text, [array, initial])
        elif t.text == "(":
            left = self.expr()
            self.need(")")
        elif t.text == "[":
            items = []
            if self.t.text != "]":
                items.append(self.expr())
                while self.accept(","):
                    items.append(self.expr())
            self.need("]")
            left = Expr("array", t, args=items)
        elif t.text.startswith('"'):
            try:
                value = json.loads(t.text)
                value.encode("utf-8")
            except (ValueError, UnicodeError):
                raise Diagnostic("G001", "invalid JSON string escape or Unicode scalar", t) from None
            left = Expr("str", t, value)
        elif t.text[0:1].isdigit():
            kind = "f64" if any(x in t.text for x in ".eE") else "i64"
            left = Expr(kind, t, t.text)
        elif t.text in {"true", "false"}:
            left = Expr("bool", t, t.text)
        elif IDENT.fullmatch(t.text) and t.text not in RESERVED | {"NEWLINE", "EOF", "INDENT", "DEDENT"}:
            left = Expr("name", t, t.text)
        else:
            raise Diagnostic("G002", "expected expression", t)
        while True:
            if self.accept("("):
                if left.kind != "name":
                    raise Diagnostic("G002", "only named functions can be called", left.token)
                args = []
                if self.t.text != ")":
                    args.append(self.expr())
                    while self.accept(","):
                        args.append(self.expr())
                self.need(")")
                left = Expr("call", left.token, left.value, args)
            elif self.accept("["):
                index = self.expr()
                self.need("]")
                left = Expr("index", left.token, args=[left, index])
            elif self.t.text in PREC and PREC[self.t.text] >= minimum:
                op = self.pop()
                right = self.expr(PREC[op.text] + 1)
                left = Expr("binary", op, op.text, [left, right])
            else:
                return left


def parse(source):
    return Parser(source).parse()
