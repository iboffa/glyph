import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from glyph.backend import Emitter, compile_c
from glyph.gc_support import collector_object, include_flags
from glyph.checker import check
from glyph.formatter import format_source
from glyph.syntax import Diagnostic, parse
from test_glyph import BUILD, ROOT, execute, native


class GuiTests(unittest.TestCase):
    def test_signatures_and_reservations(self):
        cases = [
            ('gui_window("Hello", 320)', "G107"),
            ('gui_window("Hello", true, 240)', "G102"),
            ('gui_button(1, 2, 0, 0, 40, 40)', "G102"),
            ('gui_number(1, 2)', "G102"),
            ('gui_text("label", "text")', "G102"),
            ('gui_next(1)', "G107"),
            ('gui_close(false)', "G107"),
        ]
        for call, code in cases:
            with self.subTest(call=call):
                with self.assertRaises(Diagnostic) as caught:
                    check(parse("main>void\n  " + call + "\n"))
                self.assertEqual(caught.exception.code, code)
        for source in ("gui_next = 1\nmain>void\n  print(0)\n",
                       "type gui_button\n  x:int\nmain>void\n  print(0)\n"):
            with self.assertRaises(Diagnostic) as caught:
                check(parse(source))
            self.assertEqual(caught.exception.code, "G103")

    def test_optional_backend_and_formatting(self):
        console = Emitter().emit(check(parse("main>void\n  print(1)\n")))
        self.assertNotIn("glyph_ui_", console)
        for name in ("gui_hello", "calculator"):
            source = (ROOT / "examples" / (name + ".gly")).read_text()
            formatted = format_source(source)
            self.assertEqual(format_source(formatted), formatted)
            generated = Emitter().emit(check(parse(formatted)))
            self.assertIn("#define GLYPH_GUI 1\n", generated)
            self.assertLess(generated.index("void glyph_ui_window"),
                            generated.index("static void f_main"))
        BUILD.mkdir(parents=True, exist_ok=True)
        path = BUILD / "gui_unsupported.c"
        path.write_text(generated)
        with patch("glyph.backend.sys.platform", "linux"):
            with self.assertRaises(Diagnostic) as caught:
                compile_c(path, BUILD / "gui_unsupported")
        self.assertEqual(caught.exception.code, "G203")

    def test_calculator_logic(self):
        # Exercise the actual example's state machine without creating a window.
        source = (ROOT / "examples" / "calculator.gly").read_text().split("\nmain>void")[0]
        source += """
run keys:[int]>void
  calc := Calculator.make()
  for key:keys
    calc.press(key)
  print(calc.number())
  print(calc.error)
main>void
  run([3, 14, 4, 13])
  run([9, 15, 4, 13])
  run([7, 16, 8, 13])
  run([9, 17, 3, 13])
  run([2, 11, 6, 14, 3, 11, 3, 6, 13])
  run([3, 14, 4, 16, 5, 13])
  run([9, 14, 15, 4, 13])
  run([6, 12, 16, 3, 13])
  run([9, 17, 1, 13])
  run([9, 17, 1, 13, 18, 5])
  run([3, 14, 4, 13, 8])
  run([3, 14, 4, 13, 13])
  run([12, 6, 14, 3, 13])
  run([6, 14, 12, 3, 13])
  run([2, 11, 11, 6])
  run([9, 17, 1, 13, 6])
  calc := Calculator.make()
  calc.entry = 1e100
  calc.press(16)
  calc.press(10)
  calc.press(13)
  print(calc.error)
"""
        result = execute(native(source, "gui_calculator_logic"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "5\nfalse\n5\nfalse\n42\nfalse\n4\nfalse\n"
                         "3.75\nfalse\n20\nfalse\n5\nfalse\n-10\nfalse\n"
                         "0\ntrue\n4\nfalse\n7\nfalse\n5\nfalse\n"
                         "-3\nfalse\n3\nfalse\n1.5\nfalse\n0\ntrue\ntrue\n")

    @unittest.skipUnless(sys.platform == "darwin", "AppKit backend requires macOS")
    def test_native_builds_and_runtime_errors(self):
        # These programs fail before creating an AppKit application or window.
        for index, call in enumerate(('gui_number(1, 2.0)', 'gui_next()',
                                      'gui_label(1, "x", 0, 0, 20, 20)',
                                      'gui_window("x", 0, 20)')):
            result = execute(native("main>void\n  " + call + "\n", f"gui_error_{index}"))
            self.assertEqual(result.returncode, 70, result.stderr)
            self.assertIn('"code":"R008"', result.stderr)
            self.assertIn('"line":2', result.stderr)
        for name in ("gui_hello", "calculator"):
            source = (ROOT / "examples" / (name + ".gly")).read_text()
            native(source, name)

    @unittest.skipUnless(sys.platform == "darwin" and os.environ.get("GLYPH_TEST_GUI") == "1",
                         "set GLYPH_TEST_GUI=1 in a macOS desktop session for real window tests")
    def test_appkit_controls_and_lifecycle(self):
        BUILD.mkdir(parents=True, exist_ok=True)
        exe = BUILD / "gui_macos_harness"
        # Real generated functions allocate on the Glyph heap while AppKit
        # copies text and dispatches events. The harness checks both lifetimes.
        source = '''gc_title>str = concat("Glyph GUI", " test")
gc_views>[str]
  text := concat("prefix-", "survives")
  ret [slice(text, 7, len(text))]
gc_noise>void
  for i:range(100)
    text := concat("temporary-", str_i64(i))
    gui_text(1, text)
main>void
  ret
'''
        generated = Emitter().emit(check(parse(source))).replace(
            "int main(int argc, char **argv)", "int glyph_program_entry(int argc, char **argv)")
        header = BUILD / "gui_gc_program.h"
        header.write_text(generated, encoding="utf-8")
        cache = BUILD / "gui-gc-cache"
        cache.mkdir(exist_ok=True)
        obj = collector_object(["xcrun", "clang"], cache, os.environ.copy())
        result = subprocess.run(
            ["xcrun", "clang", "-O2", "-fobjc-arc", "-std=c11", "-D_DARWIN_C_SOURCE",
             *include_flags(), "-include", str(header),
             str(Path(__file__).with_name("gui_macos_harness.m")),
             str(obj), "-framework", "AppKit", "-o", str(exe)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with patch.dict(os.environ, GLYPH_GC_STRESS="1"):
            result = execute(exe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GUI lifecycle passed", result.stdout)
