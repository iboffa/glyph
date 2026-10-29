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
    path: str = ""


class Diagnostic(Exception):
    def __init__(self, code, message, token):
        super().__init__(message)
        self.code, self.message, self.token = code, message, token

    def record(self, path):
        t = self.token
        return {"code": self.code, "severity": "error", "message": self.message,
                "file": t.path or str(path), "span": {"start": {"line": t.line, "column": t.col},
                "end": {"line": t.line, "column": t.end}}}


@dataclass
class Expr:
    kind: str
    token: Token
    value: object = None
    args: list = field(default_factory=list)
    typ: str = ""
    target: object = None


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
    owner: str = ""
    mut: bool = False
    static: bool = False
    private: bool = False
    type_params: list = field(default_factory=list)
    noalloc: bool = False


@dataclass
class Field:
    name: str
    typ: str
    token: Token
    private: bool = False


@dataclass
class Record:
    name: str
    token: Token
    fields: list = field(default_factory=list)
    methods: list = field(default_factory=list)
    type_params: list = field(default_factory=list)


@dataclass
class Union(Record):
    variants: list = field(default_factory=list)


@dataclass
class Interface(Record):
    pass


@dataclass
class Import:
    names: list
    path: str
    token: Token


LEX = re.compile(r'"(?:[^"\\\r\n]|\\.)*"|[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|[A-Za-z_][A-Za-z_0-9]*|==|!=|<=|>=|:=|\+=|-=|\*=|/=|%=|[@.+*/%<>=!,:()\[\]>\-]')
IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
RESERVED = {"if", "else", "while", "for", "ret", "unsafe", "scope", "true", "false", "and", "or", "not", "fold", "import", "from"}
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
            if line[pos] == "@" and pos != width:
                raise Diagnostic("G001", "annotation must precede a declaration", Token("@", number, pos + 1, pos + 2))
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
    def __init__(self, source, path=""):
        self.tokens, self.i = lex(source), 0
        for token in self.tokens:
            token.path = str(path)

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
            item = self.type()
            self.need("]")
            return f"[{item}]"
        if self.accept("*"):
            return "*" + self.type()
        token = self.name()
        if token.text == "fn" and self.accept("("):
            items = []
            if self.t.text != ")":
                items.append(self.type())
                while self.accept(","):
                    items.append(self.type())
            self.need(")")
            self.need(">")
            return "fn(" + ",".join(items) + ")>" + self.type()
        if self.accept("["):
            items = [self.type()]
            while self.accept(","):
                items.append(self.type())
            self.need("]")
            return token.text + "[" + ",".join(items) + "]"
        return token.text

    def type_parameters(self):
        params = []
        if self.accept("["):
            while True:
                token = self.name()
                constraint = self.name().text if self.accept(":") else ""
                params.append((token.text, constraint, token))
                if not self.accept(","):
                    break
            self.need("]")
        return params

    def parse(self):
        result = []
        while self.t.text != "EOF":
            if self.t.text == "import":
                if any(not isinstance(d, Import) for d in result):
                    raise Diagnostic("G002", "imports must precede declarations", self.t)
                result.append(self.import_statement())
                continue
            if (self.t.text in {"type", "union", "interface"} and self.i + 2 < len(self.tokens)
                    and self.tokens[self.i + 2].text in {"NEWLINE", "["}):
                result.append(self.record())
                continue
            contract = bool(self.accept("@"))
            if contract:
                self.need("noalloc")
                self.accept("NEWLINE")
            name = self.name()
            fn = self.function(name)
            fn.noalloc = contract
            result.append(fn)
        return result

    def import_statement(self):
        token = self.need("import")
        names = [self.name()]
        while self.accept(","):
            names.append(self.name())
        self.need("from")
        path = self.pop()
        if not path.text.startswith('"'):
            raise Diagnostic("G002", "import path must be a string literal", path)
        try:
            value = json.loads(path.text)
            value.encode("utf-8")
        except (ValueError, UnicodeError):
            raise Diagnostic("G001", "invalid JSON string escape or Unicode scalar", path) from None
        self.need("NEWLINE")
        return Import(names, value, token)

    def function(self, name, owner="", mut=False, static=False, private=False):
        type_params = self.type_parameters()
        params = []
        while self.t.text not in {">", "="}:
            arg = self.name()
            self.need(":")
            params.append((arg.text, self.type(), arg))
            if not self.accept(","):
                break
        typ = self.type() if self.accept(">") else ""
        if not typ and self.t.text != "=":
            raise Diagnostic("G002", "omitted result type requires an expression body", self.t)
        short = bool(self.accept("="))
        if short:
            expr = self.expr()
            self.need("NEWLINE")
            body = [Stmt("ret", expr.token, args=[expr])]
        else:
            body = self.block()
        return Function(name.text, name, params, typ, body, short, owner, mut, static, private, type_params)

    def record(self):
        kind = self.pop().text
        name = self.name()
        record = {"type": Record, "union": Union, "interface": Interface}[kind](name.text, name)
        record.type_params = self.type_parameters()
        self.need("NEWLINE")
        self.need("INDENT")
        while self.t.text not in {"DEDENT", "EOF"}:
            if kind == "union":
                variant = self.name()
                fields = []
                if self.t.text != "NEWLINE":
                    while True:
                        member = self.name()
                        self.need(":")
                        fields.append(Field(member.text, self.type(), member))
                        if not self.accept(","):
                            break
                record.variants.append((variant.text, fields, variant))
                self.need("NEWLINE")
                continue
            if kind == "interface":
                mut = bool(self.accept("mut"))
                member = self.name()
                params = []
                while self.t.text != ">":
                    arg = self.name()
                    self.need(":")
                    params.append((arg.text, self.type(), arg))
                    if not self.accept(","):
                        break
                self.need(">")
                result = self.type()
                self.need("NEWLINE")
                record.methods.append(Function(member.text, member, params, result, [], owner=name.text, mut=mut))
                continue
            contract = bool(self.accept("@"))
            if contract:
                self.need("noalloc")
                self.accept("NEWLINE")
            private = bool(self.accept("private"))
            mut = bool(self.accept("mut"))
            static = bool(self.accept("static")) if not mut else False
            member = self.name()
            if self.accept(":"):
                if mut or static or contract:
                    raise Diagnostic("G002", "mut/static apply only to methods", member)
                record.fields.append(Field(member.text, self.type(), member, private))
                self.need("NEWLINE")
            else:
                method = self.function(member, name.text, mut, static, private)
                method.noalloc = contract
                record.methods.append(method)
        self.need("DEDENT")
        return record

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
        if self.accept("arena"):
            return Stmt("arena", t, body=self.block())
        if self.accept("borrow"):
            name = self.name().text
            self.need("=")
            value = self.expr()
            return Stmt("borrow", t, name, [value], self.block())
        if self.accept("match"):
            value = self.expr()
            self.need("NEWLINE")
            self.need("INDENT")
            arms = []
            while self.t.text not in {"DEDENT", "EOF"}:
                token = self.need("case")
                variant = self.name().text
                bindings = []
                if self.accept("("):
                    if self.t.text != ")":
                        bindings.append(self.name().text)
                        while self.accept(","):
                            bindings.append(self.name().text)
                    self.need(")")
                arms.append(Stmt("case", token, (variant, bindings), body=self.block()))
            self.need("DEDENT")
            return Stmt("match", t, args=[value], body=arms)
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
        if self.accept("scope"):
            return Stmt("scope", t, body=self.block())
        if self.accept("unsafe"):
            return Stmt("unsafe", t, body=self.block())
        if self.accept("ret"):
            args = [] if self.t.text == "NEWLINE" else [self.expr()]
            stmt = Stmt("ret", t, args=args)
        elif IDENT.fullmatch(t.text) and self.tokens[self.i + 1].text == ":=":
            name = self.name().text
            self.need(":=")
            stmt = Stmt("var", t, (name, ""), [self.expr()])
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

    def lambda_ahead(self):
        saved = self.i
        try:
            self.need("(")
            if self.t.text != ")":
                while True:
                    self.name()
                    self.need(":")
                    self.type()
                    if not self.accept(","):
                        break
            self.need(")")
            self.need(">")
            self.type()
            self.need("=")
            return True
        except Diagnostic:
            return False
        finally:
            self.i = saved

    def specialization_ahead(self):
        saved = self.i
        try:
            self.pop()
            self.type()
            while self.accept(","):
                self.type()
            self.need("]")
            return True
        except Diagnostic:
            return False
        finally:
            self.i = saved

    def expr(self, minimum=0):
        t = self.pop()
        if t.text == "fn" and self.lambda_ahead():
            self.need("(")
            params = []
            if self.t.text != ")":
                while True:
                    arg = self.name()
                    self.need(":")
                    params.append((arg.text, self.type(), arg))
                    if not self.accept(","):
                        break
            self.need(")")
            self.need(">")
            result = self.type()
            self.need("=")
            left = Expr("lambda", t, (params, result), [self.expr()])
        elif t.text in {"-", "not"}:
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
                args = []
                if self.t.text != ")":
                    args.append(self.expr())
                    if self.accept("for"):
                        if left.kind != "name" or left.value not in {"sum", "count"}:
                            raise Diagnostic("G002", "generator expressions require sum or count", left.token)
                        bindings = [self.name()]
                        while self.accept(","):
                            bindings.append(self.name())
                        self.need("in")
                        source = self.expr()
                        zipped = source.kind == "call" and source.value == "zip"
                        sources = source.args if zipped else [source]
                        self.need(")")
                        left = Expr("reduce", left.token, (left.value, bindings, zipped), args + sources)
                        continue
                    while self.accept(","):
                        args.append(self.expr())
                self.need(")")
                if left.kind == "field":
                    left = Expr("method_call", left.token, left.value, left.args + args)
                elif left.kind == "name":
                    left = Expr("call", left.token, left.value, args)
                else:
                    left = Expr("invoke", left.token, args=[left] + args)
            elif self.accept("."):
                member = self.name()
                left = Expr("field", member, member.text, [left])
            elif self.t.text == "[" and left.kind == "name" and self.specialization_ahead():
                self.pop()
                items = [self.type()]
                while self.accept(","):
                    items.append(self.type())
                self.need("]")
                left = Expr("specialize", left.token, (left.value, items))
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
