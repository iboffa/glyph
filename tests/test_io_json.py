import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from glyph.checker import check
from glyph.syntax import Diagnostic, parse
from test_glyph import BUILD, native, execute


class BinaryIOTests(unittest.TestCase):
    def test_unicode_paths_arguments_and_file_identity(self):
        exe = native('''main>void
  print(try_write_bytes(arg(0), [0, 255, 42]).ok)
  print(try_read_bytes(arg(0)).value[1])
  print(file_exists(arg(0)))
  print(same_file(arg(0), arg(1)))
  print(same_file(arg(0), arg(2)))
  print(json_quote(arg(3)))
''', 'binary_unicode_paths')
        with tempfile.TemporaryDirectory(dir=BUILD) as directory:
            path = Path(directory) / '文件 🙂.bin'
            alias = Path(directory) / 'alias ü.bin'
            other = Path(directory) / 'other.bin'
            path.touch()
            os.link(path, alias)
            other.touch()
            argument = 'café 🙂 "quoted" \\ trailing\\'
            result = execute(exe, path, alias, other, argument)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertEqual(lines[:5], ['true', '255', 'true', 'true', 'false'])
            self.assertEqual(json.loads(lines[5]), argument)
            self.assertEqual(alias.read_bytes(), bytes([0, 255, 42]))

    def test_binary_roundtrip_and_utf8_boundary(self):
        exe = native(r'''main>void
  bytes := try_read_bytes(arg(0))
  print(bytes.ok)
  print(len(bytes.value))
  print(bytes.value[0])
  print(bytes.value[255])
  print(try_write_bytes(arg(1), bytes.value).ok)
  print(try_decode_utf8(bytes.value).code)
  text := "Café 🙂\u0000"
  print(try_decode_utf8(encode_utf8(text)).value == text)
  print(try_decode_utf8([192, 128]).ok)
  print(try_decode_utf8([237, 160, 128]).ok)
  print(try_decode_utf8([256]).ok)
  print(try_decode_utf8([-1]).ok)
  print(try_decode_utf8([]).value == "")
  print(try_write_bytes(arg(1), [0, 256]).code)
  print(len(try_read_bytes(arg(1)).value))
  print(try_read_file(arg(0)).code)
''', 'binary_roundtrip')
        with tempfile.TemporaryDirectory(dir=BUILD) as directory:
            source, target = Path(directory) / 'in.bin', Path(directory) / 'out.bin'
            payload = bytes(range(256)) * 100
            source.write_bytes(payload)
            proc = execute(exe, source, target)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, 'true\n25600\n0\n255\ntrue\nR009\ntrue\nfalse\nfalse\nfalse\nfalse\ntrue\nR009\n25600\nR009\n')
            self.assertEqual(target.read_bytes(), payload)

    def test_chunked_io_modes_eof_and_stale_handles(self):
        exe = native(r'''main>void
  f := try_open(arg(0), "w")
  print(f.ok)
  print(try_write(f.value, [0, 255, 128, 10]).value)
  print(try_write(f.value, []).value)
  print(try_read(f.value, 1).code)
  print(try_write(f.value, [-1]).code)
  print(try_flush(f.value).ok)
  print(try_close(f.value).ok)
  print(try_close(f.value).code)
  append := try_open(arg(0), "a")
  print(try_write(append.value, [42]).value)
  print(try_close(append.value).ok)
  read := try_open(arg(0), "r")
  print(read.value != f.value)
  print(try_read(f.value, 1).code)
  print(try_write(read.value, [1]).code)
  print(try_flush(read.value).code)
  print(try_read(read.value, 0).code)
  print(try_read(read.value, -1).code)
  first := try_read(read.value, 3)
  print(len(first.value))
  print(first.value[1])
  last := try_read(read.value, 3)
  print(len(last.value))
  print(last.value[1])
  eof := try_read(read.value, 3)
  print(eof.ok and len(eof.value) == 0)
  print(try_close(read.value).ok)
  print(try_read(-1, 1).code)
  print(try_open(arg(0), "w+").code)
  print(try_open(concat(arg(0), "\u0000x"), "w").code)
  print(len(try_read_bytes(arg(0)).value))
  print(try_read_bytes(concat(arg(0), ".missing")).code)
  print(try_write_bytes(arg(0), []).ok)
  print(len(try_read_bytes(arg(0)).value))
''', 'binary_streams')
        with tempfile.TemporaryDirectory(dir=BUILD) as directory:
            path = Path(directory) / 'bytes.bin'
            proc = execute(exe, path)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, 'true\n4\n0\nR010\nR009\ntrue\ntrue\nR010\n1\ntrue\ntrue\nR010\nR010\nR010\nR010\nR010\n3\n255\n2\n42\ntrue\ntrue\nR010\nR010\nR009\n5\nR010\ntrue\n0\n')
            self.assertEqual(path.read_bytes(), b'')

    @unittest.skipUnless(os.path.exists('/dev/stdin'), 'requires /dev/stdin')
    def test_binary_reader_accepts_nonseekable_input(self):
        if os.environ.get('GLYPH_SKIP_EXECUTION') == '1':
            self.skipTest('native execution explicitly disabled')
        exe = native('main>void\n  r := try_read_bytes(arg(0))\n  print(r.ok)\n  print(len(r.value))\n  print(r.value[9999])\n', 'binary_pipe')
        proc = subprocess.run([str(exe), '/dev/stdin'], input=b'\xff' * 10000,
                              capture_output=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, b'true\n10000\n255\n')

    @unittest.skipUnless(os.path.exists('/dev/full'), 'requires /dev/full')
    def test_write_flush_and_close_errors(self):
        proc = execute(native('''main>void
  print(try_write_bytes("/dev/full", [1, 2]).code)
  f := try_open("/dev/full", "w")
  try_write(f.value, [1, 2])
  print(try_flush(f.value).code)
  try_close(f.value)
  print(try_close(f.value).code)
''', 'binary_full'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'R010\nR010\nR010\n')


class JSONTests(unittest.TestCase):
    def test_collector_preserves_fragments_keys_and_open_handles(self):
        source = r'''main>void
  text := try_json_object([concat("dynamic", "-key")], ["[1,2,3]"]).value
  keys := try_json_keys(text)
  fragment := try_json_get(text, keys.value[0])
  a := try_open(arg(0), "w")
  b := try_open(arg(1), "w")
  c := try_open(arg(2), "w")
  print(try_close(b.value).ok)
  for i:range(10)
    noise := try_json_parse("{\"nested\":[{\"escaped\":\"\\ud83d\\ude42\"},true,null]}")
    print(noise.ok)
  print(keys.value[0])
  print(fragment.value)
  print(try_write(a.value, encode_utf8(fragment.value)).ok)
  print(try_write(c.value, encode_utf8(keys.value[0])).ok)
  print(try_close(a.value).ok)
  print(try_close(c.value).ok)
  print(try_read(b.value, 1).ok)
'''
        exe = native(source, 'io_json_gc_roots')
        with tempfile.TemporaryDirectory(dir=BUILD) as directory:
            paths = [Path(directory) / name for name in ('a', 'b', 'c')]
            with patch.dict(os.environ, GLYPH_GC_STRESS='1'):
                proc = execute(exe, *paths)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, 'true\n' * 11 + 'dynamic-key\n[1,2,3]\n' + 'true\n' * 4 + 'false\n')
            self.assertEqual(paths[0].read_bytes(), b'[1,2,3]')
            self.assertEqual(paths[1].read_bytes(), b'')
            self.assertEqual(paths[2].read_bytes(), b'dynamic-key')

    def test_navigation_and_construction(self):
        proc = execute(native(r'''main>void
  input := " {\"name\":\"Caf\\u00e9 \\ud83d\\ude42\",\"items\":[null,true,9007199254740993,1e9999],\"a\":1,\"\\u0061\":2} "
  parsed := try_json_parse(input)
  print(parsed.ok)
  print(try_json_kind(parsed.value).value)
  print(try_json_len(parsed.value).value)
  print(try_json_string(try_json_get(parsed.value, "name").value).value)
  items := try_json_get(parsed.value, "items").value
  print(try_json_at(items, 2).value)
  print(try_json_at(items, 3).value)
  print(try_json_at(items, 0).value)
  print(try_json_get(parsed.value, "a").value)
  print(try_json_get(parsed.value, "missing").code)
  print(try_json_at(items, -1).code)
  print(try_json_at(items, 4).code)
  print(try_json_string("1").code)
  print(try_json_len("null").code)
  print(try_json_keys("[]").code)
  for key:try_json_keys(parsed.value).value
    print(key)
  text := "quote\" slash\\ newline\n\u0000 🙂"
  print(try_json_string(json_quote(text)).value == text)
  array := try_json_array([json_quote(text), "true", "null", "-2.5e+3"])
  print(array.ok)
  print(try_json_len(array.value).value)
  obj := try_json_object(["a\"", "items"], ["42", array.value])
  print(obj.ok)
  print(try_json_get(obj.value, "a\"").value)
  print(try_json_array([]).value)
  print(try_json_object([], []).value)
  print(try_json_object(["a"], []).code)
  print(try_json_array(["nan"]).code)
  print(try_json_object(["a"], ["0 trailing"]).code)
  print(try_json_get("{\"a\":0} trailing", "a").code)
  print(try_json_get("{\"\\u0000\":null}", "\u0000").value)
''', 'json_navigation'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'true\nobject\n4\nCafé 🙂\n9007199254740993\n1e9999\nnull\n2\n' +
                         'R012\n' * 6 + 'name\nitems\na\na\ntrue\ntrue\n4\ntrue\n42\n[]\n{}\n' + 'R012\n' * 4 + 'null\n')

    def test_strict_grammar_and_nesting(self):
        valid = ['null', 'true', 'false', '0', '-0', '1.25', '1E+9', '1e-9999', '[]', '{}',
                 '"\\u0000"', '"\\ud800\\udc00"', '"é🙂"', '"\\/\\b\\f\\n\\r\\t\\\\\\\""',
                 '[' * 128 + '0' + ']' * 128]
        invalid = ['', ' ', '+1', '01', '-01', '.1', '1.', '1e', '1e+', '--1', 'NaN', 'Infinity',
                   'true false', '[1,]', '[,1]', '{"a":1,}', '{a:1}', '{"a" 1}', '[1 2]',
                   '"\\x"', '"\\u12"', '"\\ud800"', '"\\udc00"', '"\\ud800\\u0041"',
                   '"\n"', '"unterminated', '"escape\\', '\ufeffnull', '\vnull', 'null\x00',
                   '[' * 129 + '0' + ']' * 129]
        sources = ', '.join(json.dumps(x, ensure_ascii=True) for x in valid + invalid)
        proc = execute(native('main>void\n  for text:[' + sources + ']\n    r := try_json_parse(text)\n    print(r.ok)\n    if not r.ok\n      print(r.code == "R012" and r.value == "" and len(r.message) > 0)\n', 'json_grammar'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'true\n' * len(valid) + 'false\ntrue\n' * len(invalid))
        deep = json.dumps('[' * 128 + '0' + ']' * 128)
        proc = execute(native('main>void\n  print(try_json_array([' + deep + ']).code)\n', 'json_build_depth'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'R012\n')

    def test_seeded_serialization_roundtrips(self):
        rng = random.Random(8259)
        def value(depth=0):
            choices = [None, True, False, rng.randint(-10**18, 10**18), rng.uniform(-1e30, 1e30),
                       ''.join(rng.choices('ab\x00\n\t"\\é🙂', k=rng.randrange(30)))]
            if depth < 3:
                choices += [[value(depth+1) for _ in range(rng.randrange(4))],
                            {str(i): value(depth+1) for i in range(rng.randrange(4))}]
            return rng.choice(choices)
        values = [value() for _ in range(100)]
        # Exercise parse/serialize via the public constructor and quote/decode paths.
        texts = [json.dumps(x, ensure_ascii=bool(i % 2)) for i, x in enumerate(values)]
        source = 'main>void\n  for text:[' + ','.join(json.dumps(x) for x in texts) + ']\n    print(try_json_array([text]).value)\n    print(try_json_string(json_quote(text)).value == text)\n'
        proc = execute(native(source, 'json_seeded'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 200)
        for i, expected in enumerate(values):
            self.assertEqual(json.loads(lines[2*i]), [expected])
            self.assertEqual(lines[2*i+1], 'true')

    def test_signatures_and_result_records(self):
        cases = [('try_read("x", 1)', 'G102'), ('try_write(1, [true])', 'G102'),
                 ('try_json_parse(1)', 'G102'), ('try_json_at("[]")', 'G107'),
                 ('try_json_object([1], ["null"])', 'G102'),
                 ('BytesResult(true, ["bad"], "", "")', 'G102'),
                 ('StringsResult(true, [1], "", "")', 'G102')]
        for call, code in cases:
            with self.subTest(call=call), self.assertRaises(Diagnostic) as caught:
                check(parse('main>void\n  ' + call + '\n'))
            self.assertEqual(caught.exception.code, code)
        proc = execute(native('''type Box
  binary:BytesResult
  keys:StringsResult
main>void
  b := Box(BytesResult(true, [255], "", ""), StringsResult(true, ["key"], "", ""))
  print(b.binary.value[0])
  print(b.keys.value[0])
''', 'io_json_records'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, '255\nkey\n')
