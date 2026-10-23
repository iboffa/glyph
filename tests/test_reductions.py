"""Inference, fused reduction semantics, and checked SIMD boundary cases."""
import json
import random
import unittest

from glyph.backend import Emitter, compile_c
from glyph.checker import check
from glyph.formatter import format_source
from glyph.syntax import Diagnostic, parse
from test_glyph import BUILD, execute, native


class InferenceTests(unittest.TestCase):
    def test_forward_inference_and_aliases(self):
        source = """first a:[int] = second(a)
second a:[i64] = sum(a)
main = first([1, 2])
"""
        functions = check(parse(source))
        self.assertEqual([f.result for f in functions], ["i64"] * 3)
        self.assertEqual(functions[0].params[0][1], "[i64]")
        # An explicit result breaks a recursive inference dependency.
        check(parse("a n:int>int = b(n)\nb n:int = a(n)\nmain = 0\n"))

    def test_rejections(self):
        cases = [
            ("a = a()\nmain = 0\n", "G111"),
            ("a = b()\nb = a()\nmain = 0\n", "G111"),
            ("main>void\n  a := []\n", "G102"),
            ("main>void\n  a := print(1)\n", "G102"),
            ("main>void\n  a := 1\n  a = true\n", "G102"),
            ("main>void\n  a := 1\n  a := 2\n", "G103"),
            ("main>void\n  a = 1\n", "G101"),
            ("main>void\n  print(sum([true]))\n", "G102"),
            ("main>void\n  print(count([1]))\n", "G102"),
            ("main>void\n  print(sum([]))\n", "G102"),
            ("main>void\n  print(sum(true for x in [1]))\n", "G102"),
            ("main>void\n  print(count(x for x in [1]))\n", "G102"),
            ("main>void\n  print(sum(x for x in 1))\n", "G102"),
            ("main>void\n  print(sum(x for x in [1]))\n  print(x)\n", "G101"),
            ("main>void\n  x := 0\n  print(sum(x for x in [1]))\n", "G103"),
            ("main>void\n  print(sum(x for x, x in zip([1], [2])))\n", "G103"),
            ("main>void\n  print(sum(x for x in zip([1], [2])))\n", "G107"),
            ("main>void\n  print(sum(x for x in zip([1])))\n", "G107"),
            ("main>void\n  print(sum(x for x in zip()))\n", "G107"),
            ("main>void\n  print(sum(x for x, y in [1]))\n", "G107"),
            ("main>void\n  print(len(x for x in [1]))\n", "G002"),
            ("main>void\n  print(sum(x for x in [1] if x > 0))\n", "G002"),
            ("bad x:int, x:int = x\nmain = 0\n", "G103"),
            ("bad x:void = x\nmain = 0\n", "G103"),
        ]
        for source, code in cases:
            with self.subTest(source=source):
                with self.assertRaises(Diagnostic) as caught:
                    check(parse(source))
                self.assertEqual(caught.exception.code, code)
                self.assertGreaterEqual(caught.exception.token.line, 1)

    def test_formatter_preserves_inference(self):
        source = """# examples
solve a:[int],b:[int]=sum(x*y for x,y in zip(a,b))
main>void
    a:= [1,2] # inferred
    b:[int]=[3,4]
    print(solve(a,b))
    print(count(x>0 for x in a))
"""
        formatted = format_source(source)
        self.assertEqual(formatted, format_source(formatted))
        self.assertIn("a := [1, 2]", formatted)
        self.assertIn("solve a:[int], b:[int] = sum(", formatted)
        self.assertIn("# inferred", formatted)
        check(parse(formatted))

    def test_malformed_reduction_diagnostics(self):
        rng = random.Random(773)
        tokens = ["sum", "count", "zip", "for", "in", ":=", "int", "x", ",",
                  "(", ")", "[", "]", "1", "true", "+", "="]
        for _ in range(500):
            source = "main>void\n  " + " ".join(rng.choices(tokens, k=rng.randint(1, 18))) + "\n"
            try:
                check(parse(source))
            except Diagnostic:
                pass


class ReductionTests(unittest.TestCase):
    def test_reducers_and_evaluation_order(self):
        source = """dot a:[int], b:[int] = sum(x * y for x, y in zip(a, b))
positives a:[int] = count(x > 0 for x in a)
announce a:[int], id:int>[int]
  print(id)
  ret a
bump a:[int], x:int>int
  a[1] += 10
  ret x
main>void
  a := [1, 2, 3]
  empty:[int] = []
  print(sum(a))
  print(sum(empty))
  print(dot(a, [4, 5, 6]))
  print(dot(empty, empty))
  print(positives([-2, 0, 3, 7]))
  print(positives(empty))
  print(count([true, false, true]))
  flags:[bool] = []
  print(count(flags))
  print(sum([1.5, 2.5]))
  print(sum([1e16, 1.0, -1e16]))
  print(sum(x for x in [1e16, 1.0, -1e16]))
  floats:[f64] = []
  print(sum(floats))
  print(sum(sum(y for y in [3, 4]) + x for x in a))
  print(sum(x + y for x, y in zip(announce([1], 8), announce([2], 9))))
  print(sum(bump(a, x) for x in a))
  print(a[1])
  print(count(false and bump(a, x) > 0 for x in a))
  print(a[1])
  print(sum(len(s) for s in ["a", "λ"]))
  b := [1, 2]
  print(sum(bump(b, x) + y for x, y in zip(b, b)))
  print(b[1])
  print(sum(x + y + z for x, y, z in zip([1], [2], [3])))
  unsafe
    p:*int = ptr(b)
    print(load(p))
  sum(bump(b, x) for x in b)
  print(b[1])
"""
        expected = "6\n0\n32\n0\n2\n0\n2\n0\n4\n0\n0\n0\n27\n8\n9\n3\n16\n32\n0\n32\n3\n26\n22\n6\n1\n42\n"
        for name, text in [("reduce", source), ("reduce_fmt", format_source(source))]:
            with self.subTest(name=name):
                proc = execute(native(text, name))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout, expected)

    def test_zip_length_failure_precedes_body(self):
        source = """announce a:[int], id:int>[int]
  print(id)
  ret a
main>void
  print(sum(1 / 0 + x + y for x, y in zip(announce([1], 8), announce([], 9))))
"""
        proc = execute(native(source, "zip_length"))
        self.assertEqual(proc.returncode, 70, proc.stderr)
        self.assertEqual(proc.stdout, "8\n9\n")
        diagnostic = json.loads(proc.stderr)
        self.assertEqual(diagnostic["code"], "R007")
        self.assertEqual(diagnostic["span"]["start"]["line"], 5)

    def test_ordinary_calls_can_use_existing_sum_function(self):
        source = """sum a:[int] = len(a)
count a:[int] = len(a)
main>void
  print(sum([8, 9]))
  print(count([8, 9]))
  print(sum(x for x in [8, 9]))
"""
        proc = execute(native(source, "reducer_names"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "2\n2\n17\n")

    def test_generator_overflow_and_sequencing(self):
        # The last item would bring the final sum back into range, but the
        # second prefix must trap, before the third item's observable print.
        source = """observe x:int>int
  print(x)
  ret x
main>void
  print(sum(observe(x) for x in [9223372036854775807, 1, -1]))
"""
        proc = execute(native(source, "generator_trap"))
        self.assertEqual(proc.returncode, 70, proc.stderr)
        self.assertEqual(proc.stdout, "9223372036854775807\n1\n")
        self.assertEqual(json.loads(proc.stderr)["code"], "R001")

    def test_guarded_sum_prefix_reference(self):
        source = """reduce a:[int], initial:int = fold a initial +
main>void
  n := argi(0)
  initial := argi(1)
  mode := argi(2)
  a := fill(n, 0)
  i := 0
  while i < n
    a[i] = argi(i + 3)
    i += 1
  if mode == 0
    print(reduce(a, initial))
  else
    print(sum(a))
"""
        lo, hi, slack = -(1 << 63), (1 << 63) - 1, 1 << 39
        cases = []
        for n in [0, 1, 255, 256, 257, 511, 512, 513]:
            for initial in [0, lo + slack, hi - slack, lo + slack - 1, hi - slack + 1]:
                for value in [-(1 << 31), (1 << 31) - 1]:
                    cases.append((initial, [value] * n))
        for n in [0, 255, 256, 511, 512]:
            for tail in [[hi, 1, -1], [lo, -1, 1], [hi, -hi], [lo, hi, 1]]:
                cases.append((0, [0] * n + tail))
        rng = random.Random(20261020)
        for _ in range(40):
            values = [lo, hi, -(1 << 40), -1, 0, 1, 1 << 40]
            cases.append((rng.choice(values), rng.choices(values, k=rng.choice([2, 256, 513]))))
        BUILD.mkdir(parents=True, exist_ok=True)
        c = BUILD / "guarded_sum.c"
        c.write_text(Emitter().emit(check(parse(source))))
        for optimization in ["0", "2", "3"]:
            exe = BUILD / ("guarded_sum_O" + optimization + ".exe")
            compile_c(c, exe, optimization)
            for initial, items in cases:
                total, overflow = initial, False
                for item in items:
                    total += item
                    if total < lo or total > hi:
                        overflow = True
                        break
                for mode in ([0, 1] if initial == 0 else [0]):
                    with self.subTest(optimization=optimization, initial=initial, n=len(items), mode=mode):
                        proc = execute(exe, len(items), initial, mode, *items)
                        self.assertEqual(proc.returncode, 70 if overflow else 0, proc.stderr)
                        if overflow:
                            error = json.loads(proc.stderr)
                            self.assertEqual(error["code"], "R001")
                            self.assertEqual(error["span"]["start"]["line"], 1 if mode == 0 else 14)
                        else:
                            self.assertEqual(proc.stdout, str(total) + "\n")


if __name__ == "__main__":
    unittest.main()
