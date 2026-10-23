"""Exercise file imports through both public compiler drivers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from glyph.formatter import format_source
from glyph.syntax import Diagnostic, parse

ROOT = Path(__file__).resolve().parents[1]


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.drivers = [('python', [sys.executable, '-m', 'glyph'])]
        if os.environ.get('GLYPH_SELFHOST'):
            self.drivers.append(('native', [os.environ['GLYPH_SELFHOST']]))

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def invoke(self, driver, command='check', source='main.gly', extra=()):
        name, argv = driver
        args = [*argv, command, str(self.root / source), '--json']
        if command in ('run', 'build'):
            args += ['-o', str(self.root / (name + '-program'))]
            if name == 'native':
                args += ['--runtime-dir', str(ROOT / 'glyph')]
        return subprocess.run([*args, *map(str, extra)], cwd=ROOT, capture_output=True,
                              text=True, timeout=60)

    def run_all(self, expected):
        for driver in self.drivers:
            with self.subTest(driver=driver[0]):
                result = self.invoke(driver, 'run')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)

    def error_all(self, code, file='main.gly', line=None):
        for driver in self.drivers:
            with self.subTest(driver=driver[0]):
                result = self.invoke(driver)
                self.assertEqual(result.returncode, 1, result.stderr)
                diagnostic = json.loads(result.stderr)
                self.assertEqual(diagnostic['code'], code, diagnostic)
                self.assertEqual(Path(diagnostic['file']).resolve(), (self.root / file).resolve())
                if line:
                    self.assertEqual(diagnostic['span']['start']['line'], line)

    def test_nested_diamond_imports_and_local_helpers(self):
        self.write('shared.gly', 'type Item\n  value:int\n\nmake n:int>Item = Item(n)\n')
        self.write('left/a.gly', 'import Item, make from "../shared.gly"\n'
                   'helper n:int>int = n + 1\nleft n:int>Item = make(helper(n))\n')
        self.write('right.gly', 'import Item from "./shared.gly"\n'
                   'helper n:int>int = n * 2\nright x:Item>int = helper(x.value)\n')
        self.write('main.gly', 'import left from "left/a.gly"\nimport right from "./right.gly"\n'
                   'main>void\n  print(right(left(20)))\n')
        self.run_all('42\n')

    def test_records_methods_arrays_and_shadowed_names(self):
        self.write('types.gly', 'type Counter\n  value:int\n'
                   '  static create n:int>Counter = Counter(n)\n'
                   '  mut add n:int>void\n    self.value += n\n'
                   'type Box\n  counters:[Counter]\n'
                   'apply Counter:Counter>int = Counter.value\n')
        self.write('main.gly', 'import Counter, Box, apply from "./types.gly"\n'
                   'main>void\n  x:Counter = Counter.create(4)\n  x.add(3)\n'
                   '  box := Box([x])\n  print(apply(box.counters[0]))\n'
                   '  values := [1, 2, 3]\n  print(sum(Counter for Counter in values))\n')
        self.run_all('7\n6\n')

    def test_self_receiver_and_module_type_name(self):
        self.write('types.gly', 'type self\n  value:int\n'
                   '  static create n:int>self = self(n)\n'
                   '  read>int = self.value\n')
        self.write('main.gly', 'import self from "./types.gly"\n'
                   'main>void\n  x := self.create(8)\n  print(x.read())\n')
        self.run_all('8\n')

    def test_unimported_names_do_not_leak_or_reexport(self):
        self.write('lib.gly', 'helper>int = 4\npublic>int = helper()\n')
        self.write('wrapper.gly', 'import public from "./lib.gly"\nwrapper>int = public()\n')
        for name in ('helper', 'gmod1_helper'):
            self.write('main.gly', f'import public from "./lib.gly"\nmain = {name}()\n')
            self.error_all('G101')
        self.write('main.gly', 'import public from "./wrapper.gly"\nmain = public()\n')
        self.error_all('G401')

    def test_conflicts_missing_names_and_module_main(self):
        self.write('lib.gly', 'answer>int = 42\n')
        for source in ('import missing from "./lib.gly"\nmain = 0\n',
                       'import answer, answer from "./lib.gly"\nmain = 0\n',
                       'import answer from "./lib.gly"\nanswer = 1\nmain = 0\n'):
            self.write('main.gly', source)
            self.error_all('G401')
        self.write('lib.gly', 'main = 0\nanswer = 42\n')
        self.write('main.gly', 'import answer from "./lib.gly"\nmain = answer()\n')
        self.error_all('G401', 'lib.gly', 1)

    def test_cycles_and_path_aliases(self):
        self.write('main.gly', 'import answer from "./a.gly"\nmain = answer()\n')
        self.write('a.gly', 'import value from "./b.gly"\nanswer = value()\n')
        self.write('b.gly', 'import answer from "./a.gly"\nvalue = answer()\n')
        self.error_all('G402', 'b.gly', 1)
        self.write('b.gly', 'value = 3\n')
        (self.root / 'alias.gly').symlink_to(self.root / 'b.gly')
        self.write('main.gly', 'import answer from "./a.gly"\nimport value from "./alias.gly"\n'
                   'main>void\n  print(answer() + value())\n')
        self.run_all('6\n')
        self.write('b.gly', 'import value from "./alias.gly"\nvalue = 3\n')
        self.error_all('G402', 'b.gly')

    def test_bad_paths_and_syntax(self):
        for path in ('missing.gly', './lib.txt', '/absolute.gly', 'bad\x00.gly'):
            self.write('main.gly', 'import x from ' + json.dumps(path) + '\nmain = 0\n')
            self.error_all('G400', line=1)
        self.write('lib.gly', 'x = 1\n')
        for source in ('main = 0\nimport x from "./lib.gly"\n',
                       'import x from 1\nmain = 0\n',
                       'import x from ("./lib.gly")\nmain = 0\n',
                       'main>void\n  import x from "./lib.gly"\n'):
            self.write('main.gly', source)
            self.error_all('G002')

    def test_unicode_paths_and_inferred_import_results(self):
        self.write('space ü/helpers 🙂.gly', 'answer = 42\n')
        self.write('main.gly', 'import answer from "space ü/helpers 🙂.gly" # relative path\n'
                   'main>void\n  print(answer())\n')
        self.run_all('42\n')

    def test_module_graph_limits(self):
        self.write('main.gly', 'import value from "./m0.gly"\nmain = value()\n')
        for index in range(128):
            source = (f'import value from "./m{index + 1}.gly"\n' if index < 127 else '')
            self.write(f'm{index}.gly', source)
        self.error_all('G005', 'm126.gly', 1)
        self.write('m0.gly', '#' + 'x' * 1048576)
        self.error_all('G005', 'main.gly', 1)

    def test_imported_diagnostics_and_privacy(self):
        self.write('main.gly', 'import broken from "./lib.gly"\nmain = broken()\n')
        self.write('lib.gly', 'broken>int\n  ret "wrong"\n')
        self.error_all('G102', 'lib.gly', 2)
        self.write('lib.gly', 'broken>int\n  ret @\n')
        self.error_all('G001', 'lib.gly', 2)
        self.write('lib.gly', 'type Secret\n  private value:int\n'
                   '  static create>Secret = Secret(7)\n')
        self.write('main.gly', 'import Secret from "./lib.gly"\nmain = Secret.create().value\n')
        self.error_all('G112', 'main.gly', 2)

    def test_runtime_diagnostics_track_caller_after_imported_call(self):
        self.write('lib.gly', 'value>int = 5\nexplode n:int>int = 10 / n\n')
        for body, file, line in (('print(explode(0))', 'lib.gly', 2),
                                  ('print(value() / 0)', 'main.gly', 3)):
            self.write('main.gly', 'import value, explode from "./lib.gly"\nmain>void\n  ' + body + '\n')
            for driver in self.drivers:
                with self.subTest(driver=driver[0], file=file):
                    result = self.invoke(driver, 'run')
                    self.assertEqual(result.returncode, 70, result.stderr)
                    d = json.loads(result.stderr)
                    self.assertEqual(d['code'], 'R002')
                    self.assertEqual(Path(d['file']).resolve(), (self.root / file).resolve())
                    self.assertEqual(d['span']['start']['line'], line)

    def test_protects_all_imported_source_outputs(self):
        content = 'answer = 42\n'
        lib = self.write('lib.gly', content)
        alias = self.root / 'alias.gly'
        alias.symlink_to(lib)
        self.write('main.gly', 'import answer from "./lib.gly"\nmain = answer()\n')
        for driver in self.drivers:
            for target in (lib, alias):
                result = self.invoke(driver, 'build', extra=('-o', target))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('G004', result.stderr)
                self.assertEqual(lib.read_text(), content)
            # The generated C path must also protect imported files.
            if driver[0] == 'python':
                result = self.invoke(driver, 'build', extra=('--emit-c', lib))
            else:
                result = self.invoke(driver, 'emit-c', extra=('-o', lib))
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('G004', result.stderr)
            self.assertEqual(lib.read_text(), content)

    def test_format_imports_without_resolving_files(self):
        source = '# files need not exist during formatting\nimport Foo,bar from "./ünicode.gly"\nmain=0\n'
        formatted = format_source(source)
        self.assertIn('import Foo, bar from "./ünicode.gly"', formatted)
        self.assertEqual(format_source(formatted), formatted)
        self.assertEqual(len(parse(formatted)), 2)
