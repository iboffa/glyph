"""Default collector correctness and bounded-heap regression checks."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from benchmarks.memory_cases import CASES, STRESS, STRESS_EXPECTED
from glyph.backend import Emitter, compile_c
from glyph.checker import check
from glyph.gc_support import VENDOR
from glyph.syntax import parse
from test_glyph import BUILD, execute


class GcTests(unittest.TestCase):
    def build(self, source, name, optimization="2", harness=""):
        BUILD.mkdir(parents=True, exist_ok=True)
        generated = Emitter().emit(check(parse(source)))
        if harness:
            generated = generated.replace("int main(int argc, char **argv)",
                                          "int glyph_program_entry(int argc, char **argv)")
        c = BUILD / (name + ".c")
        c.write_text(generated + harness, encoding="utf-8")
        exe = c.with_suffix(".exe" if os.name == "nt" else "")
        compile_c(c, exe, optimization)
        return exe

    def test_vendor_integrity(self):
        manifest = json.loads((VENDOR / "UPSTREAM.json").read_text())
        for relative, digest in manifest["files_sha256"].items():
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256((VENDOR / relative).read_bytes()).hexdigest(), digest)

    def test_live_graphs_survive_collection_at_all_optimization_levels(self):
        for optimization in ("0", "2", "3"):
            with self.subTest(optimization=optimization):
                exe = self.build(STRESS, "gc_roots_O" + optimization, optimization)
                with patch.dict(os.environ, GLYPH_GC_STRESS="1"):
                    result = execute(exe)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, STRESS_EXPECTED)

    def test_temporary_arrays_strings_and_cycles_have_bounded_heap(self):
        # Call actual generated functions. No forced GC: automatic collection
        # must reclaim discarded batches instead of retaining them until exit.
        batches = 4096
        for name in ("numeric", "text", "cycles"):
            with self.subTest(workload=name):
                harness = r'''
int main(void) {
    g_gc_init();
    int64_t total = 0;
    for (int64_t i = 0; i < 4096; ++i) total += f_work(i);
    printf("%lld %llu %llu\n", (long long)total,
           (unsigned long long)GC_get_total_bytes(),
           (unsigned long long)GC_get_heap_size());
    return 0;
}
'''
                exe = self.build(CASES[name]["source"], "gc_reclaim_" + name, harness=harness)
                result = execute(exe)
                self.assertEqual(result.returncode, 0, result.stderr)
                checksum, allocated, heap = map(int, result.stdout.split())
                self.assertEqual(checksum, CASES[name]["expected"](batches))
                self.assertGreater(allocated, 16 * 1024 * 1024)
                self.assertLess(heap, 8 * 1024 * 1024)

    def test_inline_records_zero_length_and_scanned_nested_records(self):
        source = """type Pair
  x:int
  y:f64
type Box
  pair:Pair
type Keep
  box:Box
  text:str
  items:[int]
main>void
  numbers := [Box(Pair(7, 1.25))]
  copied := clone(numbers)
  numbers = push(numbers, Box(Pair(9, 2.5)))
  keep := [Keep(copied[0], concat("keep-", "alive"), [42])]
  empty:[Box] = []
  empty = clone(empty)
  empty = push(empty, numbers[1])
  for i:range(100)
    noise := fill(2048, i)
  print(keep[0].text)
  print(keep[0].items[0])
  print(keep[0].box.pair.x)
  print(empty[0].pair.y)
"""
        exe = self.build(source, "gc_record_layouts")
        with patch.dict(os.environ, GLYPH_GC_STRESS="1"):
            result = execute(exe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "keep-alive\n42\n7\n2.5\n")


if __name__ == "__main__":
    unittest.main()
