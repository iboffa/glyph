import contextlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest

from glyph.syntax import parse, Diagnostic
from glyph.checker import check
from glyph.backend import Emitter, compile_c
from glyph.formatter import format_source
from glyph.cli import main

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "tests"


def native(source, name):
    BUILD.mkdir(parents=True, exist_ok=True)
    c = BUILD / (name + ".c")
    c.write_text(Emitter().emit(check(parse(source))), encoding="utf-8")
    exe = BUILD / (name + (".exe" if os.name == "nt" else ""))
    compile_c(c, exe)
    return exe


def execute(exe, *args):
    if os.environ.get("GLYPH_SKIP_EXECUTION") == "1":
        raise unittest.SkipTest("native execution explicitly disabled by host policy; compilation completed")
    return subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True, encoding="utf-8", timeout=20)


class FrontendTests(unittest.TestCase):
    def test_rejections(self):
        cases = [
            ("main>void\n  print(x)\n", "G101"),
            ("main>void\n  x:i64 = true\n", "G102"),
            ("main>void\n  x:i64 = 1\n  x:i64 = 2\n", "G103"),
            ("main>void\n  1 = 2\n", "G104"),
            ("main>void\n  print(9223372036854775808)\n", "G105"),
            ("main>i64\n  if true\n    ret 1\n", "G106"),
            ("main>void\n  print()\n", "G107"),
            ("f>i64 = 1\n", "G108"),
            ("main>void\n  ret\n  print(1)\n", "G109"),
            ("main>void\n  a:[i64] = [1]\n  p:*i64 = ptr(a)\n", "G110"),
            ("main>void\n\tprint(1)\n", "G001"),
            ('main>void\n  print("oops)\n', "G001"),
            ('main>void\n  print("\\q")\n', "G001"),
            ("main>void\n  x = 1\n", "G101"),
            ("main>void\n  x:i32 = 1\n", "G003"),
            ("main>void\n  if 1\n    print(1)\n", "G102"),
            ("main>void\n  print([1, true])\n", "G102"),
            ("main>void\n  a:[i64] = [1]\n  print(a[true])\n", "G102"),
            ("main>void\n  if true\n    x:i64 = 1\n  print(x)\n", "G101"),
            ("main>void\n  print(1 + 1.0)\n", "G102"),
            ("main>void\n  print(1e999)\n", "G105"),
            ("main>void\n  for x:1\n    print(x)\n", "G102"),
            ("main>void\n  a:[i64] = [1]\n  print(a == a)\n", "G102"),
            ("main>void\n  x:void = print(1)\n", "G102"),
            ("main>void\n  main()\n", "G104"),
        ]
        for source, code in cases:
            with self.subTest(source=source):
                with self.assertRaises(Diagnostic) as caught:
                    check(parse(source))
                self.assertEqual(caught.exception.code, code)
                self.assertGreaterEqual(caught.exception.token.line, 1)

    def test_formatter(self):
        sources = [p.read_text(encoding="utf-8") for p in (ROOT / "examples").glob("*.gly")]
        sources += ['# head\nmain>void\n    x:i64=1+2*3 # trailing\n    print("# text")\n# tail\n',
                    'main>i64\n  # retained\n  ret 1\n',
                    'main>void\n  print((fold [1,2] 0 +) * 3)\n',
                    'main>void\n  print((1+2)*3)\n  print(1-(2-3))\n']
        for source in sources:
            with self.subTest(source=source):
                formatted = format_source(source)
                self.assertEqual(format_source(formatted), formatted)
                check(parse(formatted))
        self.assertIn('# trailing', format_source(sources[-4]))

    def test_diagnostic_span(self):
        with self.assertRaises(Diagnostic) as caught:
            check(parse("main>void\n  print(missing)\n"))
        record = caught.exception.record("test.gly")
        self.assertEqual(record["span"], {"start": {"line": 2, "column": 9}, "end": {"line": 2, "column": 16}})

    def test_malformed_sources_never_crash(self):
        rng = random.Random(1701)
        tokens = ["ret", "if", "for", "[", "]", "(", ")", "1", "a", ":", ">", "i64", "+", "=", "true", "fold"]
        for _ in range(500):
            source = "main>void\n  " + " ".join(rng.choices(tokens, k=rng.randint(1, 15))) + "\n"
            try:
                check(parse(source))
            except Diagnostic:
                pass

    def test_cli_json_and_format_check(self):
        BUILD.mkdir(parents=True, exist_ok=True)
        p = BUILD / "bad.gly"
        p.write_text("main>void\n  print(missing)\n")
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            self.assertEqual(main(["check", str(p), "--json"]), 1)
        self.assertEqual(json.loads(stream.getvalue())["code"], "G101")
        p.write_text("main>i64=0\n")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["fmt", str(p), "--check"]), 1)
        self.assertEqual(main(["fmt", str(p)]), 0)
        self.assertEqual(main(["fmt", str(p), "--check"]), 0)


class NativeTests(unittest.TestCase):
    def test_examples(self):
        outputs = {"hello": "Hello from Glyph\n42\n", "sum": "15\n15\n", "collections": "4\n10\n2\n3\n42\n0\ntrue\n2\ntrue\ntrue\n", "unsafe": "10\n42\n", "fibonacci": "6765\n", "reductions": "3\n2\n18\n", "records": "25\n32\n5\n3\n7\n"}
        executables = {}
        for name in outputs:
            source = (ROOT / "examples" / (name + ".gly")).read_text(encoding="utf-8")
            executables[name] = native(source, name)
        for name, expected in outputs.items():
            with self.subTest(name=name):
                proc = execute(executables[name])
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout, expected)

    def test_semantics(self):
        source = '''bump a:[i64]>i64
  a[0] += 1
  ret a[0]

pair a:i64, b:i64>i64 = a * 10 + b

make>[i64] = [3, 4]

sum a:[i64]>i64
  s:i64 = 0
  for x:a
    s += x
  ret s

main>void
  a:[i64] = [0]
  print(pair(bump(a), bump(a)))
  print(false and bump(a) > 0)
  print(true or bump(a) > 0)
  print(a[0])
  a[0] += bump(a)
  print(a[0])
  b:[i64] = a
  b[0] = 7
  print(a[0])
  c:[i64] = clone(a)
  c[0] = 8
  print(a[0])
  d:[i64] = make()
  print(sum(d))
  print(fold d 0 +)
  print(fold d 1 *)
  empty:[f64] = []
  print(fold empty 2.5 +)
  flags:[bool] = fill(3, true)
  flags[1] = false
  print(flags[1])
  fs:[f64] = [1.5, 2.5]
  print(fold fs 0.0 +)
  print(-7 / 3)
  print(-7 % 3)
  print(-9223372036854775808)
  print(i64(3.75))
  print(f64(2) / 4.0)
  print("λ" == "\\u03bb")
  print("a\\u0000b" != "a")
  i:i64 = 0
  while i < 3
    i += 1
  if i == 3
    print("yes")
  else
    print("no")
'''
        expected = "12\nfalse\ntrue\n2\n5\n7\n7\n7\n7\n12\n2.5\nfalse\n4\n-2\n-1\n-9223372036854775808\n3\n0.5\ntrue\ntrue\nyes\n"
        executables = [native(text, variant) for variant, text in (("semantics", source), ("formatted", format_source(source)))]
        for exe in executables:
            proc = execute(exe)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, expected)

    def test_runtime_traps(self):
        source = '''main>void
  mode:i64 = argi(0)
  x:i64 = argi(1)
  a:[i64] = [1]
  if mode == 0
    print(x + 1)
  if mode == 1
    print(x / 0)
  if mode == 2
    print(a[x])
  if mode == 3
    b:[i64] = range(x)
    print(len(b))
  if mode == 4
    print(x / -1)
  if mode == 5
    print(x * 2)
  if mode == 6
    print(-x)
  if mode == 7
    print(i64(1e30))
  if mode == 8
    print(x % -1)
'''
        exe = native(source, "traps")
        cases = [(0, 2**63-1, "R001"), (1, 1, "R002"), (2, -1, "R003"), (2, 1, "R003"), (3, -1, "R004"), (4, -2**63, "R001"), (5, 2**62, "R001"), (6, -2**63, "R001"), (7, 0, "R006"), (8, -2**63, "R001"), (0, "bad", "R005")]
        for mode, value, code in cases:
            with self.subTest(mode=mode, value=value):
                proc = execute(exe, mode, value)
                self.assertEqual(proc.returncode, 70, proc.stderr)
                error = json.loads(proc.stderr)
                self.assertEqual(error["code"], code)
                self.assertGreater(error["span"]["start"]["line"], 1)

    def test_random_arithmetic_differential(self):
        rng = random.Random(482)
        source, expected = ["main>void"], []
        for _ in range(150):
            a, b = rng.randint(-10000, 10000), rng.randint(1, 10000)
            op = rng.choice(["+", "-", "*", "/", "%"])
            q = abs(a) // b * (-1 if a < 0 else 1)
            value = {"+": a+b, "-": a-b, "*": a*b, "/": q, "%": a-q*b}[op]
            source.append(f"  print({a} {op} {b})")
            expected.append(str(value))
        proc = execute(native("\n".join(source) + "\n", "differential"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), expected)

    def test_cli_run_arguments_exit_and_build(self):
        p = BUILD / "exit.gly"
        p.write_text("main>i64 = argi(0)\n")
        command = [sys.executable, "-m", "glyph"]
        proc = subprocess.run(command + ["build", str(p), "-O3", "-o", str(BUILD / "cli.exe")], capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if os.environ.get("GLYPH_SKIP_EXECUTION") == "1":
            self.skipTest("native execution explicitly disabled by host policy; CLI build completed")
        proc = subprocess.run(command + ["run", str(p), "--", "7"], capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 7, proc.stderr)
        self.assertEqual(execute(BUILD / "cli.exe", 0).returncode, 0)


if __name__ == "__main__":
    unittest.main()
