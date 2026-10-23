import json
import random
import unittest

from glyph.syntax import Diagnostic, parse
from glyph.checker import check
from glyph.backend import Emitter, compile_c
from glyph.formatter import format_source
from test_glyph import BUILD, execute, native


POINT = """type Point
  x:int
  get = self.x
  mut add n:int>void
    self.x += n
  mut replace n:int>void
    self = Point(n)
  snapshot ignored:int = self.x
  mut live ignored:int = self.x
  static zero = Point(0)
"""


class RecordFrontendTests(unittest.TestCase):
    def reject(self, source, code):
        with self.assertRaises(Diagnostic) as caught:
            check(parse(source))
        self.assertEqual(caught.exception.code, code)

    def test_invalid_layouts_and_members(self):
        cases = [
            ("type A\n  x:Missing\n", "G003"),
            ("type A\n  x:void\n", "G102"),
            ("type A\n  x:A\n", "G113"),
            ("type A\n  b:B\ntype B\n  a:A\n", "G113"),
            ("type A\n  x:int\n  x:int\n", "G103"),
            ("type A\n  x:int\n  x = 1\n", "G103"),
            ("type A\n  f = 1\n", "G102"),
            ("type int\n  x:int\n", "G103"),
            ("type A\n  x:int\ntype A\n  y:int\n", "G103"),
            ("type A\n  x:int\nA = 0\n", "G103"),
            ("type A\n  x:int\n  f self:int = self\n", "G103"),
            ("type A\n  x:int\n  f = self.g()\n  g = self.f()\n", "G111"),
            ("type A\n  x:int\n  mut x:int\n", "G002"),
        ]
        for declaration, code in cases:
            with self.subTest(declaration=declaration):
                self.reject(declaration + "main>void\n  print(0)\n", code)

    def test_invalid_calls_and_mutation(self):
        cases = [
            ("p := Point(1)\n  p.missing = 2", "G101"),
            ("p := Point(1)\n  p.missing()", "G101"),
            ("Point(1).add(2)", "G104"),
            ("Point(1).x = 2", "G104"),
            ("Point.add(2)", "G104"),
            ("p := Point(1)\n  p.zero()", "G104"),
            ("p := Point(1)\n  p.add()", "G107"),
            ("p := Point(1)\n  p.add(true)", "G102"),
            ("p := Point()", "G107"),
            ("p := Point(true)", "G102"),
            ("print(Point(1))", "G102"),
            ("print(Point(1) == Point(1))", "G102"),
            ("unsafe\n    print(ptr([Point(1)]))", "G102"),
        ]
        for body, code in cases:
            with self.subTest(body=body):
                self.reject(POINT + "main>void\n  " + body + "\n", code)
        for body in ("self.x = 2", "self = Point(2)", "self.add(2)"):
            self.reject(POINT + "  bad>void\n    " + body + "\nmain>void\n  print(0)\n", "G112")

    def test_privacy(self):
        private = """type Secret
  private value:int
  private hidden = self.value
  static make n:int = Secret(n)
  get = self.hidden()
"""
        for body in ("s := Secret(1)", "s := Secret.make(1)\n  print(s.value)",
                     "s := Secret.make(1)\n  s.hidden()"):
            self.reject(private + "main>void\n  " + body + "\n", "G112")
        self.reject(private + "type Other\n  value:int\n  steal s:Secret = s.value\nmain>void\n  print(0)\n", "G112")
        check(parse(private + "main>void\n  print(Secret.make(3).get())\n"))

    def test_forward_types_recursion_and_contextual_type_name(self):
        check(parse("""type Outer
  inner:Inner
type Inner
  children:[Outer]
  value:int
  recurse n:int>int
    if n == 0
      ret self.value
    ret self.recurse(n - 1)
type n:int = n
main>void
  o := Outer(Inner([], type(3)))
  print(o.inner.recurse(2))
"""))

    def test_formatter_and_malformed_records(self):
        source = "# head\n" + POINT + """  # factory comment
  static other>Point
    # body comment
    ret Point(2)
main>void
  p:=Point.zero() # use
  p.add(2)
  print(p.get())
# tail
"""
        formatted = format_source(source)
        self.assertEqual(format_source(formatted), formatted)
        check(parse(formatted))
        for comment in ("head", "factory comment", "body comment", "use", "tail"):
            self.assertIn("# " + comment, formatted)
        rng = random.Random(92)
        tokens = ["type", "Point", "private", "mut", "static", ".", "self",
                  ":", ">", "int", "[", "]", "(", ")", "=", "1", "NEWLINE"]
        for _ in range(500):
            source = "type A\n  " + " ".join(rng.choices(tokens, k=rng.randint(1, 15))) + "\nmain>void\n  print(0)\n"
            try:
                check(parse(source))
            except Diagnostic:
                pass


class RecordNativeTests(unittest.TestCase):
    def run_variants(self, source, expected, name):
        BUILD.mkdir(parents=True, exist_ok=True)
        for opt in ("0", "2", "3"):
            with self.subTest(optimization=opt):
                text = format_source(source) if opt == "2" else source
                c = BUILD / f"{name}_{opt}.c"
                c.write_text(Emitter().emit(check(parse(text))))
                exe = BUILD / f"{name}_{opt}"
                compile_c(c, exe, optimization=opt)
                proc = execute(exe)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout, expected)

    def test_copy_composition_and_arrays(self):
        source = POINT + """type Box
  point:Point
  samples:[int]
  touch>void
    self.samples[0] += 1
type Tree
  children:[Tree]
  value:int
change p:Point>Point
  p.add(10)
  ret p
main>void
  a := Box(Point(1), [5])
  b := a
  b.point.add(2)
  b.touch()
  print(a.point.x)
  print(b.point.x)
  print(a.samples[0])
  c := change(b.point)
  print(c.x)
  print(b.point.x)
  c.replace(7)
  print(c.x)
  values := fill(2, a)
  values[0].point.add(3)
  print(values[1].point.x)
  copy := clone(values)
  copy[0].point.add(10)
  print(values[0].point.x)
  copy[0].touch()
  print(a.samples[0])
  grown := push(values, b)
  print(sum(item.point.x for item in grown))
  for item:grown
    item.point.add(100)
  print(grown[0].point.x)
  tree := Tree([Tree([], 8)], 9)
  print(tree.children[0].value)
  print(Point.zero().get())
"""
        self.run_variants(source, "1\n3\n6\n13\n3\n7\n1\n4\n7\n8\n4\n8\n0\n", "record_copies")

    def test_receiver_snapshot_reference_and_evaluation_order(self):
        source = POINT + """index log:[int]>int
  log[0] += 1
  ret 0
change values:[Point]>int
  values[0].x = 20
  ret 3
make values:[Point]>[Point] = values
main>void
  values := [Point(1)]
  log := [0]
  print(values[index(log)].snapshot(change(values)))
  print(log[0])
  values[0].x = 1
  print(values[index(log)].live(change(values)))
  print(log[0])
  values[0].x = 1
  values[index(log)].x += change(values)
  print(values[0].x)
  print(log[0])
  make(values)[0].add(2)
  print(values[0].x)
"""
        self.run_variants(source, "1\n1\n20\n2\n4\n3\n6\n", "record_order")

    def test_private_factory_and_inferred_methods(self):
        source = """type Counter
  private value:int
  private twice = self.value * 2
  static start n:int = Counter(n)
  get = self.twice()
  mut add n:int>void
    self.value += n
main>void
  c := Counter.start(3)
  c.add(2)
  print(c.get())
"""
        proc = execute(native(source, "record_private"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "10\n")

    def test_runtime_traps(self):
        source = POINT + """main>void
  values := [Point(argi(1))]
  if argi(0) == 0
    values[0].add(1)
  else
    values[argi(1)].add(1)
"""
        exe = native(source, "record_traps")
        for mode, value, code in ((0, 2**63 - 1, "R001"), (1, -1, "R003"), (1, 1, "R003")):
            proc = execute(exe, mode, value)
            self.assertEqual(proc.returncode, 70, proc.stderr)
            self.assertEqual(json.loads(proc.stderr)["code"], code)
