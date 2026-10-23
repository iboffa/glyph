import os
from pathlib import Path
import tempfile
import unittest

from glyph.backend import Emitter, compile_c
from glyph.checker import check
from glyph.formatter import format_source
from glyph.modules import load_program
from glyph.syntax import Diagnostic, parse
from test_glyph import BUILD, native, execute


class ResultTests(unittest.TestCase):
    def test_parsing_recovers_and_retains_independent_results(self):
        source = r'''main>void
  good := try_parse_i64("-9223372036854775808")
  for text:["", "-", "+1", " 1", "1 ", "1x", "9223372036854775808", "-9223372036854775809", "1\u0000"]
    bad := try_parse_i64(text)
    print(bad.ok)
    print(bad.value)
    print(bad.code)
    print(len(bad.message) > 0)
  print(good.ok)
  print(good.value)
  print(good.code == "" and good.message == "")
  print(try_parse_i64("9223372036854775807").value)
  print(try_parse_i64("00042").value)
  for text:["", "-", "nan", "inf", "1e999", "1x", " 1", "1 ", "1\u0000"]
    bad := try_parse_f64(text)
    print(bad.ok)
    print(bad.value)
    print(bad.code)
    print(len(bad.message) > 0)
  for text:["1.25e2", "+.5", "-1e-9999"]
    good_float := try_parse_f64(text)
    print(good_float.ok)
    print(good_float.code == "" and good_float.message == "")
    print(valid_f64(text))
  print(try_parse_f64("1.25e2").value)
  print("continued")
'''
        proc = execute(native(source, 'results_parse'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, '')
        self.assertEqual(proc.stdout, 'false\n0\nR009\ntrue\n' * 9 +
                         'true\n-9223372036854775808\ntrue\n9223372036854775807\n42\n' +
                         'false\n0\nR009\ntrue\n' * 9 + 'true\ntrue\ntrue\n' * 3 + '125\ncontinued\n')

    def test_files_recover_and_do_not_truncate_nul_paths(self):
        BUILD.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BUILD) as directory:
            folder = Path(directory)
            good, invalid, missing = folder / 'text ü.txt', folder / 'invalid', folder / 'missing'
            good.write_text('keep', encoding='utf-8')
            invalid.write_bytes(b'\xff')
            source = r'''main>void
  nul_path := concat(arg(0), "\u0000suffix")
  for path:[arg(2), arg(1), nul_path]
    failed := try_read_file(path)
    print(failed.ok)
    print(failed.value == "")
    print(failed.code)
    print(len(failed.message) > 0)
  bad_write := try_write_file(nul_path, "lost")
  print(bad_write.ok)
  print(bad_write.value)
  print(bad_write.code)
  print(read_file(arg(0)))
  bad_dir := try_write_file(arg(3), "lost")
  print(bad_dir.ok)
  print(bad_dir.code)
  wrote := try_write_file(arg(0), "hello 🙂\u0000")
  print(wrote.ok and wrote.value)
  print(wrote.code == "" and wrote.message == "")
  read := try_read_file(arg(0))
  print(read.ok)
  print(read.value == "hello 🙂\u0000")
  print(read.code == "" and read.message == "")
  try_write_file(arg(0), "")
  empty := try_read_file(arg(0))
  print(empty.ok and empty.value == "")
  print("continued")
'''
            exe = native(source, 'results_files')
            proc = execute(exe, good, invalid, missing, folder)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, '')
            self.assertEqual(proc.stdout, 'false\ntrue\nR010\ntrue\n' +
                             'false\ntrue\nR009\ntrue\n' * 2 +
                             'false\nfalse\nR009\nkeep\nfalse\nR010\n' + 'true\n' * 6 + 'continued\n')
            self.assertEqual(good.read_bytes(), b'')

    @unittest.skipUnless(os.path.exists('/dev/full'), '/dev/full is required for a deterministic write failure')
    def test_write_or_close_failure_recovers(self):
        proc = execute(native('''main>void
  r := try_write_file("/dev/full", "cannot fit")
  print(r.ok)
  print(r.code)
  print("continued")
''', 'results_full'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'false\nR010\ncontinued\n')

    def test_process_failures_and_child_exit(self):
        source = r'''main>void
  empty := try_process([])
  print(empty.ok)
  print(empty.code)
  missing := try_process(["/glyph-missing-executable-for-results"])
  print(missing.ok)
  print(missing.code)
  nul := try_process(["bad\u0000name"])
  print(nul.ok)
  print(nul.code)
  if platform() != "windows"
    child := try_process(["/bin/sh", "-c", "exit 7"])
    print(child.ok)
    print(child.value)
    print(child.code == "" and child.message == "")
  print("continued")
'''
        proc = execute(native(source, 'results_process'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, '')
        expected = 'false\nR010\nfalse\nR010\nfalse\nR009\n'
        if os.name != 'nt':
            expected += 'true\n7\ntrue\n'
        self.assertEqual(proc.stdout, expected + 'continued\n')

    def test_custom_errors_propagation_collections_and_modules(self):
        BUILD.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BUILD) as directory:
            folder = Path(directory)
            helper = folder / 'helper.gly'
            helper.write_text('''positive text:str>IntResult
  parsed := try_parse_i64(text)
  if not parsed.ok
    ret parsed
  if parsed.value <= 0
    ret IntResult(false, 0, "positive", "expected a positive number")
  ret parsed
''')
            source = '''import positive from "./helper.gly"
type Batch
  results:[IntResult]
main>void
  b := Batch([positive("bad"), positive("0"), positive("42")])
  for result:b.results
    print(result.ok)
    print(result.value)
    print(result.code)
  values := list(b.results)
  print(values.get(1).message)
  print(StringResult(true, "custom", "", "").value)
  print(FloatResult(true, 2.5, "", "").value)
  print(BoolResult(true, true, "", "").value)
'''
            entry = folder / 'main.gly'
            formatted = format_source(source)
            self.assertEqual(format_source(formatted), formatted)
            entry.write_text(formatted)
            output = folder / 'main.c'
            output.write_text(Emitter().emit(check(load_program(entry))))
            exe = folder / ('main.exe' if os.name == 'nt' else 'main')
            compile_c(output, exe)
            proc = execute(exe)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, 'false\n0\nR009\nfalse\n0\npositive\ntrue\n42\n\nexpected a positive number\ncustom\n2.5\ntrue\n')

    def test_type_errors(self):
        cases = [
            ('main>void\n  try_parse_i64(1)\n', 'G102'),
            ('main>void\n  try_write_file("x")\n', 'G107'),
            ('main>void\n  r:IntResult = try_parse_f64("1")\n', 'G102'),
            ('main>void\n  print(try_parse_i64("1").missing)\n', 'G101'),
            ('main>void\n  IntResult(true, "wrong", "", "")\n', 'G102'),
            ('type IntResult\n  x:int\nmain>void\n  print(1)\n', 'G103'),
            ('IntResult>void\n  print(1)\nmain>void\n  print(1)\n', 'G103'),
        ]
        for source, code in cases:
            with self.subTest(source=source):
                with self.assertRaises(Diagnostic) as caught:
                    check(parse(source))
                self.assertEqual(caught.exception.code, code)
