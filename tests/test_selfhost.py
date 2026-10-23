import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_glyph import ROOT


@unittest.skipUnless(os.environ.get('GLYPH_SELFHOST'), 'set GLYPH_SELFHOST to a bootstrapped glyphc')
class SelfhostDriverTests(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([os.environ['GLYPH_SELFHOST'], *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)

    def test_run_arguments_and_utf8_paths(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            source = Path(directory) / 'quoted "ü".gly'
            source.write_text('main>void\n  print(arg(0))\n  print(argc())\n', encoding='utf-8')
            argument = 'spaces; $(literal) "quotes" 🙂'
            result = self.invoke('run', source, '-o', Path(directory) / 'native program',
                                 '--runtime-dir', ROOT / 'glyph', '--', argument)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, argument + '\n1\n')

    def test_protects_source_and_aliases(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            source = Path(directory) / 'source.gly'
            text = 'main = 0\n'
            source.write_text(text)
            alias = Path(directory) / 'alias.gly'
            alias.symlink_to(source)
            for output in (source, alias):
                for command in ('build', 'emit-c'):
                    result = self.invoke(command, source, '-o', output)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn('G004', result.stderr)
                    self.assertEqual(source.read_text(), text)

    def test_literal_edges_and_line_endings(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            source = Path(directory) / 'literals.gly'
            program = ('\t# ignored comment\nmain>void\n'
                       '  print(-09223372036854775808)\n'
                       '  print("\\ud83d\\ude42")\n'
                       '  print("Café")\n')
            for newline in ('\n', '\r\n', '\r'):
                source.write_bytes(program.replace('\n', newline).encode())
                result = self.invoke('run', source, '-o', Path(directory) / 'literals',
                                     '--runtime-dir', ROOT / 'glyph')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '-9223372036854775808\n🙂\nCafé\n')
            for invalid in ('main>void\n  print(é)\n', 'main>void\n  print(1+é)\n',
                            'main>void\n  print("\\ud800")\n'):
                source.write_text(invalid)
                result = self.invoke('check', source)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(json.loads(result.stderr)['code'], 'G001')
