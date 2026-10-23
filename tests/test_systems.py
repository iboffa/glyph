import json
from pathlib import Path
import subprocess
import unittest

from glyph.checker import check
from glyph.syntax import Diagnostic, parse
from test_glyph import BUILD, ROOT, native, execute


class SystemsTests(unittest.TestCase):
    def test_text_and_unicode(self):
        source = '''main>void
  s := concat("Caf", chr(233))
  print(s)
  print(len(s))
  print(byte_at(s, 3))
  print(slice(s, 0, 3))
  print(slice(s, 3, 5))
  print(join(["a", "b", "unused"], 2, "/"))
  print(join([], 0, "/"))
  print(str_i64(-9223372036854775808))
  print(parse_i64("00042"))
  print(parse_f64("1.25e2"))
  print(valid_f64("1e999"))
  print(chr(128578))
'''
        proc = execute(native(source, 'systems_text'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'Café\n5\n195\nCaf\né\na/b\n\n-9223372036854775808\n42\n125\nfalse\n🙂\n')

    def test_runtime_errors(self):
        cases = [('slice("é", 0, 1)', 'R009'), ('byte_at("x", 1)', 'R003'),
                 ('chr(55296)', 'R009'), ('parse_i64("9223372036854775808")', 'R009'),
                 ('parse_i64("-")', 'R009'), ('parse_f64("nan")', 'R009'),
                 ('join(["x"], 2, "")', 'R003'), ('arg(100)', 'R005'),
                 ('read_file("/glyph-test-file-that-does-not-exist")', 'R010'),
                 ('getenv("bad\\u0000name")', 'R009')]
        for i, (expr, code) in enumerate(cases):
            with self.subTest(expr=expr):
                proc = execute(native('main>void\n  print(' + expr + ')\n', f'systems_error_{i}'))
                self.assertEqual(proc.returncode, 70, proc.stderr)
                self.assertEqual(json.loads(proc.stderr)['code'], code)

    def test_files_arguments_and_process(self):
        target = BUILD / 'systems path ü.txt'
        source = '''main>void
  print(argc())
  path := arg(0)
  write_file(path, "hello 🙂\\n")
  print(read_file(path))
  print(same_file(path, path))
  print(file_exists(path))
  print(file_exists(concat(path, ".missing")))
  if platform() != "windows"
    print(process(["/usr/bin/printf", "%s", arg(1)]))
'''
        exe = native(source, 'systems_files')
        proc = execute(exe, target, 'literal $(not-a-command); spaced argument')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('hello 🙂\n', proc.stdout)
        self.assertIn('true\ntrue\nfalse\n', proc.stdout)
        self.assertEqual(target.read_text(), 'hello 🙂\n')
        if 'literal' in proc.stdout:
            self.assertIn('literal $(not-a-command); spaced argument', proc.stdout)

    def test_signatures(self):
        for call, code in [('slice("x", 0)', 'G107'), ('byte_at("x", true)', 'G102'),
                           ('process([1])', 'G102'), ('write_file("x", 1)', 'G102')]:
            with self.assertRaises(Diagnostic) as caught:
                check(parse('main>void\n  ' + call + '\n'))
            self.assertEqual(caught.exception.code, code)
