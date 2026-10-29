import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from glyph.syntax import Diagnostic, parse
from glyph.checker import check
from glyph.backend import Emitter, compile_c
from glyph.analysis import Analysis
from glyph.formatter import format_source

ROOT = Path(__file__).resolve().parents[1]
NATIVE = Path(os.environ.get('GLYPH_MEMORY_NATIVE', ROOT / 'build/memory-selfhost/glyphc'))

POSITIVE = '''@noalloc small x:int>int
  a := fill(4, x)
  bias := 2
  f := fn(y:int)>int = y + bias
  ret f(sum(a))
copy_out n:int>[int]
  arena
    a := arena_fill(n, 3)
    a[0] = 7
    ret managed(a)
early n:int>int
  b := owned_fill(n, 4)
  borrow a = b
    if n > 0
      ret a[0]
  ret 0
main>void
  print(small(5))
  print(sum(copy_out(4)))
  b := owned_fill(4, 2)
  borrow a = b
    a[0] = 9
    print(sum(a))
  c := move(b)
  free(c)
  print(early(3))
'''

NEGATIVE = [
    ('main>void\n  a := arena_fill(4, 0)\n', 'G121'),
    ('f>[int]\n  arena\n    ret arena_fill(4, 0)\nmain = 0\n', 'G121'),
    ('f>[int]\n  arena\n    a := arena_fill(4, 0)\n    ret a\nmain = 0\n', 'G121'),
    ('main>void\n  a := owned_fill(4, 0)\n  b := a\n', 'G121'),
    ('main>void\n  a := owned_fill(4, 0)\n  free(a)\n  free(a)\n', 'G121'),
    ('main>void\n  a := owned_fill(4, 0)\n  b := move(a)\n  borrow x = a\n    print(x[0])\n', 'G121'),
    ('main>void\n  a := owned_fill(4, 0)\n  borrow x = a\n    free(a)\n', 'G121'),
    ('main>void\n  a := owned_fill(4, 0)\n  if true\n    free(a)\n', 'G121'),
    ('main>void\n  a := owned_fill(4, 0)\n  while false\n    b := move(a)\n', 'G121'),
    ('f>fn()>int\n  arena\n    a := arena_fill(4, 0)\n    ret fn()>int = a[0]\nmain = 0\n', 'G121'),
    ('type Box\n  a:[int]\nmain>void\n  arena\n    a := arena_fill(4, 0)\n    b := Box(a)\n', 'G121'),
    ('main>void\n  arena\n    a := arena_fill(4, 0)\n    unsafe\n      p := ptr(a)\n', 'G121'),
    ('main>void\n  arena\n    a := arena_fill(4, "managed reference")\n', 'G121'),
    ('type Box\n  text:str\nmain>void\n  a := owned_fill(4, Box("x"))\n', 'G121'),
    ('f b:buffer[int]>void\n  ret\nmain = 0\n', 'G003'),
    ('@noalloc f n:int>int\n  a := fill(n, 1)\n  ret sum(a)\nmain = 0\n', 'G120'),
    ('@noalloc f>int\n  ret len(clone([1]))\nmain = 0\n', 'G120'),
    ('@noalloc f>int\n  ret f()\nmain = 0\n', 'G120'),
    ('@noalloc f cb:fn()>int>int = cb()\nmain = 0\n', 'G120'),
    ('@noalloc f>void\n  print(1)\nmain = 0\n', 'G120'),
    ('@noalloc f>int\n  arena\n    a := arena_fill(4, 0)\n    ret a[0]\nmain = 0\n', 'G120'),
    ('f n:int>[int] = fill(n, 1)\n@noalloc g>int = len(f(4))\nmain = 0\n', 'G120'),
    ('@noalloc f[T] x:T>[T] = [x]\nmain>void\n  a := f[int](1)\n', 'G120'),
    ('main>void\n  b := owned_fill(1, 0)\n  borrow a = b\n    x := a\n', 'G121'),
    ('main>void\n  out := [0]\n  arena\n    a := arena_fill(4, 0)\n    out = a\n', 'G121'),
    ('read a:[int]>int = a[0]\nmain>void\n  arena\n    a := arena_fill(4, 0)\n    print(read(a))\n', 'G121'),
]

class MemoryControlsTests(unittest.TestCase):
    def test_negative_rules(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'negative.gly'
            for source, code in NEGATIVE:
                with self.subTest(source=source):
                    with self.assertRaises(Diagnostic) as cm:
                        check(parse(source))
                    self.assertEqual(cm.exception.code, code)
                    if NATIVE.exists():
                        path.write_text(source)
                        p = subprocess.run([NATIVE, 'check', path], capture_output=True, text=True)
                        self.assertNotEqual(p.returncode, 0, source)
                        self.assertEqual(json.loads(p.stderr)['code'], code, p.stderr)

    def test_domains_all_levels_and_gc_stress(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'positive.gly'; path.write_text(POSITIVE)
            for level in '0123':
                for optimized in (False, True):
                    with self.subTest(level=level, optimized=optimized):
                        c = Path(d) / 'ref.c'; exe = Path(d) / 'ref'
                        c.write_text(Emitter(optimized).emit(check(parse(POSITIVE))))
                        compile_c(c, exe, level, stats=True, zero_init=not optimized)
                        p = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, GLYPH_GC_STRESS='1'))
                        self.assertEqual(p.returncode, 0, p.stderr)
                        self.assertEqual(p.stdout, '22\n16\n15\n4\n')
                        stats = json.loads(p.stderr.split('GLYPH_MEMORY ')[1])
                        self.assertEqual(stats['owned_count'], 2)
                        self.assertEqual(stats['arena_count'], 1)
                if NATIVE.exists():
                    command = [NATIVE, 'build', path, '-o', Path(d)/'native', '-O'+level, '--runtime-dir', ROOT/'glyph', '--alloc-stats']
                    p = subprocess.run(command, capture_output=True, text=True, timeout=60)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    p = subprocess.run([Path(d)/'native'], capture_output=True, text=True, env=dict(os.environ, GLYPH_GC_STRESS='1'), timeout=30)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    self.assertEqual(p.stdout, '22\n16\n15\n4\n')

    def test_alias_and_pointer_fallback(self):
        source = '''main>void
  a := [1, 2]
  b := a
  a[0] = 7
  unsafe
    p := offset(ptr(b), 1)
    print(load(p))
  print(b[0])
'''
        analysis = Analysis(check(parse(source)))
        self.assertFalse(analysis.stack)

    def test_ir_order_and_reports(self):
        declarations = check(parse('main>void\n  a := [1, 2]\n  print(a[1] + 4)\n'))
        analysis = Analysis(declarations)
        self.assertEqual(analysis.ir[id(declarations[0])][0].op, 'var')
        self.assertTrue(any(r['action'] == 'bounds' and r['accepted'] for r in analysis.reports))
        self.assertTrue(analysis.stack)
        self.assertFalse(Analysis(declarations, False).stack)

    def test_format_contract_and_domains(self):
        formatted = format_source(POSITIVE)
        check(parse(formatted))
        self.assertEqual(format_source(formatted), formatted)

    def test_invalid_allocation_traps(self):
        for call in ('owned_fill(-1, 0)', 'arena_fill(-1, 0)', 'fill(9223372036854775807, 0)', 'range(9223372036854775807)', 'owned_fill(9223372036854775807, 0)', 'arena_fill(9223372036854775807, 0)'):
            source = 'main>void\n  arena\n    a := '+call+'\n'
            with tempfile.TemporaryDirectory() as d:
                c = Path(d)/'bad.c'; exe=Path(d)/'bad'
                c.write_text(Emitter().emit(check(parse(source))))
                compile_c(c, exe)
                p = subprocess.run([exe], capture_output=True, text=True)
                self.assertEqual(p.returncode, 70)
                self.assertEqual(json.loads(p.stderr)['code'], 'R004')
                if NATIVE.exists():
                    path=Path(d)/'bad.gly';path.write_text(source)
                    p=subprocess.run([NATIVE,'run',path,'-o',Path(d)/'native','--runtime-dir',ROOT/'glyph'],capture_output=True,text=True)
                    self.assertEqual(p.returncode,70,p.stderr)
                    self.assertEqual(json.loads(p.stderr)['code'],'R004')

    def test_fusion_reuse_aliases_and_error_order(self):
        source = """main>void
  n := argi(0)
  a := fill(n, 0)
  i := 0
  total := 0
  while i < 4
    a = fill(n, i)
    total += sum(a)
    i += 1
  print(total)
  print(sum(fill(n, 7)))
  print(count(fill(n, true)))
  print(sum(range(n)))
  b := fill(n, 8)
  alias := b
  b = fill(n, 9)
  print(sum(alias))
  print(sum(b))
"""
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'case.gly';path.write_text(source)
            for opt in (False, True):
                c=Path(d)/'case.c';exe=Path(d)/'case'
                c.write_text(Emitter(opt).emit(check(parse(source))))
                compile_c(c,exe,stats=True)
                p=subprocess.run([exe,'5'],capture_output=True,text=True,check=True)
                self.assertEqual(p.stdout,'30\n35\n5\n10\n40\n45\n')
                if opt:
                    counts=json.loads(p.stderr.split('GLYPH_MEMORY ')[1])
                    self.assertEqual(counts['gc_count'],3)
            if NATIVE.exists():
                p=subprocess.run([NATIVE,'run',path,'-o',Path(d)/'native','--runtime-dir',ROOT/'glyph','--','5'],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertEqual(p.stdout,'30\n35\n5\n10\n40\n45\n')
            # Fill evaluates its value before size validation; division fails first.
            for expression,code in [('sum(fill(-1, 1 / 0))','R002'),('sum(fill(-1, 1))','R004'),('sum(fill(3, 9223372036854775807))','R001')]:
                for opt in (False,True):
                    c.write_text(Emitter(opt).emit(check(parse('main>void\n  print('+expression+')\n'))))
                    compile_c(c,exe)
                    p=subprocess.run([exe],text=True,capture_output=True)
                    self.assertEqual(json.loads(p.stderr)['code'],code)

    def test_transitive_contract_generic_and_method(self):
        source = """type Box
  value:int
  @noalloc get>int = self.value
helper[T] x:T>T = x
work x:int>int
  a := [x, x]
  ret sum(a)
@noalloc caller x:int>int = work(helper[int](x)) + Box(x).get()
main>void
  print(caller(4))
"""
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'case.gly';path.write_text(source)
            for opt in (False,True):
                c=Path(d)/'case.c';exe=Path(d)/'case'
                c.write_text(Emitter(opt).emit(check(parse(source))))
                compile_c(c,exe)
                self.assertEqual(subprocess.check_output([exe],text=True),'12\n')
            if NATIVE.exists():
                p=subprocess.run([NATIVE,'run',path,'-o',Path(d)/'native','--runtime-dir',ROOT/'glyph','--no-optimize'],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertEqual(p.stdout,'12\n')

    def test_alias_initializer_and_disjoint_bindings(self):
        sources = [(
            """main>void
  original := [1, 2]
  a := original
  a = fill(2, 9)
  print(original[0])
  if true
    v := [1, 2, 3, 4]
    print(v[3])
  if true
    v := [9]
    print(v[3])
""", '1\n4\n', 70), (
            """main>void
  x := 5
  if true
    f := fn(y:int)>int = x + y
    print(f(2))
  if true
    f := fn(y:int)>int = x * y
    print(f(2))
""", '7\n10\n', 0)]
        with tempfile.TemporaryDirectory() as d:
            for source,stdout,status in sources:
                path=Path(d)/'case.gly';path.write_text(source)
                c=Path(d)/'case.c';exe=Path(d)/'case'
                c.write_text(Emitter().emit(check(parse(source))))
                compile_c(c,exe)
                p=subprocess.run([exe],capture_output=True,text=True)
                self.assertEqual((p.stdout,p.returncode),(stdout,status))
                if NATIVE.exists():
                    p=subprocess.run([NATIVE,'run',path,'-o',Path(d)/'native','--runtime-dir',ROOT/'glyph'],capture_output=True,text=True)
                    self.assertEqual((p.stdout,p.returncode),(stdout,status),p.stderr)
        for source in ('main>void\n  ret\n  arena\n    print(1)\n', 'main>void\n  a := owned_fill(1, 0)\n  ret\n  borrow b = a\n    print(b[0])\n'):
            with self.assertRaises(Diagnostic) as cm:check(parse(source))
            self.assertEqual(cm.exception.code,'G109')
            if NATIVE.exists():
                with tempfile.TemporaryDirectory() as d:
                    path=Path(d)/'bad.gly';path.write_text(source)
                    p=subprocess.run([NATIVE,'check',path],capture_output=True,text=True)
                    self.assertEqual(json.loads(p.stderr)['code'],'G109')

if __name__ == '__main__':
    unittest.main()
