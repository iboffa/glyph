"""Isolated GC/region experiments; does not change Glyph's production allocator.

Build BDWGC 8.2.12 into build/memory-deps/install first; see the experiment report.
"""
import argparse
import contextlib
from datetime import datetime
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
import unittest
from zoneinfo import ZoneInfo

from glyph import backend
from glyph.checker import check
from glyph.syntax import parse
from .memory_cases import CASES, STRESS, STRESS_EXPECTED

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/memory"
BASE_EMITTER = backend.Emitter
VARIANTS = ("arena", "region", "gc", "gc_atomic")
GC_VERSION = "8.2.12"
GC_ARCHIVE_SHA256 = "42e5194ad06ab6ffb806c83eb99c03462b495d979cda782f3c72c08af833cd4e"


def replace_function(text, name, replacement):
    import re
    match = re.search(r"^static [^\n]+\b" + name + r"\([^\n]*\) \{", text, re.M)
    if not match:
        raise ValueError("Missing runtime function: " + name)
    depth, end = 1, match.end()
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    old = text[match.start():end]
    return text[:match.start()] + replacement(old) + text[end:]


ALLOCATOR = r'''
static uint64_t bench_requested, bench_allocations;
static g_array bench_new(int64_t n, size_t size, int l, int c, bool atomic) {
    if (n < 0 || (uint64_t)n > SIZE_MAX / size)
        g_fail("R004", "invalid allocation size", l, c);
    bench_requested += (uint64_t)(n ? n : 1) * size;
    ++bench_allocations;
#if BENCH_GC
#if BENCH_FORCE_GC
    GC_gcollect();
#endif
    size_t bytes = (size_t)(n ? n : 1) * size;
    void *data = atomic ? GC_malloc_atomic(bytes) : GC_malloc(bytes);
    if (!data) g_fail("R004", "allocation failed", l, c);
    if (atomic) memset(data, 0, bytes);
    return (g_array){data, n};
#else
    (void)atomic;
    return g_arena_new(n, size, l, c);
#endif
}
static g_array g_new(int64_t n, size_t size, int l, int c) {
    return bench_new(n, size, l, c, false);
}
static g_array g_new_atomic(int64_t n, size_t size, int l, int c) {
    return bench_new(n, size, l, c, true);
}
'''
CLONE_ATOMIC = r'''
static g_array g_clone_atomic(g_array a, size_t size, int l, int c) {
    g_array b = g_new_atomic(a.len, size, l, c);
    memcpy(b.data, a.data, (size_t)a.len * size);
    return b;
}
'''
HARNESS = r'''
#include <sys/resource.h>
static int compare_double(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}
static uint64_t peak_rss(void) {
    struct rusage r;
    if (getrusage(RUSAGE_SELF, &r)) abort();
#ifdef __APPLE__
    return (uint64_t)r.ru_maxrss;
#else
    return (uint64_t)r.ru_maxrss * 1024;
#endif
}
static void region_end(g_alloc *mark) {
    while (g_allocations != mark) {
        g_alloc *p = g_allocations;
        g_allocations = p->next;
        free(p->data);
        free(p);
    }
}
int main(int argc, char **argv) {
    INIT
    g_argc = argc; g_argv = argv; atexit(g_cleanup);
    int64_t n = g_argi(0, 1, 1);
    if (n < 32 || n > 65536) return 2;
    double *latencies = malloc((size_t)n * sizeof(double));
    if (!latencies) return 3;
    SETUP
    int64_t checksum = 0;
    double start = g_clock();
    for (int64_t i = 0; i < n; ++i) {
        double before = g_clock();
        g_alloc *mark = g_allocations;
        checksum += WORK;
        RELEASE
        latencies[i] = g_clock() - before;
    }
    double elapsed = g_clock() - start;
    int64_t retained = VALIDATE;
    uint64_t rss = peak_rss();
    size_t heap = 0, heap_after = 0, free_after = 0, collections = 0;
#if BENCH_GC
    heap = GC_get_heap_size();
    collections = GC_get_gc_no();
    GC_gcollect();
    heap_after = GC_get_heap_size(); free_after = GC_get_free_bytes();
#endif
    qsort(latencies, (size_t)n, sizeof(double), compare_double);
    printf("{\"checksum\":%lld,\"retained\":%lld,\"elapsed_s\":%.9g,"
           "\"peak_rss_bytes\":%llu,\"requested_bytes\":%llu,\"allocations\":%llu,"
           "\"batch_p50_s\":%.9g,\"batch_p99_s\":%.9g,\"batch_max_s\":%.9g,"
           "\"gc_heap_bytes\":%zu,\"gc_collections\":%zu,"
           "\"gc_heap_after_collect_bytes\":%zu,\"gc_free_after_collect_bytes\":%zu}\n",
           (long long)checksum, (long long)retained, elapsed,
           (unsigned long long)rss, (unsigned long long)bench_requested,
           (unsigned long long)bench_allocations, latencies[n/2],
           latencies[(n*99-1)/100], latencies[n-1], heap, collections, heap_after, free_after);
    free(latencies);
    return 0;
}
'''


class MemoryEmitter(BASE_EMITTER):
    variant = "gc_atomic"
    force_gc = False

    def pointer_free(self, typ):
        if typ in {"i64", "f64", "bool"}:
            return True
        record = self.record_types.get(typ)
        return bool(record) and all(self.pointer_free(f.typ) for f in record.fields)

    def temp(self, typ, value):
        if self.variant == "gc_atomic" and typ.startswith("[") and self.pointer_free(typ[1:-1]):
            if value.startswith("g_new("):
                value = "g_new_atomic(" + value[len("g_new("):]
            if value.startswith("g_clone("):
                value = "g_clone_atomic(" + value[len("g_clone("):]
        return super().temp(typ, value)

    def emit(self, declarations, filename="<source>"):
        from glyph.syntax import Record
        self.record_types = {r.name: r for r in declarations if isinstance(r, Record)}
        text = super().emit(declarations, filename)
        text = replace_function(text, "g_new", lambda old: old.replace("g_new(", "g_arena_new(", 1) + ALLOCATOR)
        text = replace_function(text, "g_clone", lambda old: old + CLONE_ATOMIC)
        if self.variant == "gc_atomic":
            text = replace_function(text, "g_range", lambda old: old.replace("g_new(", "g_new_atomic("))
            for name in ("g_text", "g_cstr", "g_std_join", "g_std_read_file"):
                text = replace_function(text, name, lambda old: old.replace("g_new(", "g_new_atomic("))
        gc = self.variant.startswith("gc")
        header = f"#define BENCH_GC {int(gc)}\n#define BENCH_FORCE_GC {int(self.force_gc)}\n"
        if gc:
            header += "#include <gc/gc.h>\n"
            text = text.replace("    g_argc=argc;", "    GC_set_all_interior_pointers(1); GC_INIT();\n    g_argc=argc;")
        return header + text


def compile_experiment(source, output, prefix, optimization="2"):
    cache = ROOT / "build/.glyph-cache"
    env = os.environ.copy()
    env.update(ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache), TEMP=str(cache), TMP=str(cache))
    command = backend.compiler() + ["-x", "c", str(source), "-std=c11", "-O" + optimization,
                                  "-fno-fast-math", "-ffp-contract=off", "-D_POSIX_C_SOURCE=200809L",
                                  "-I" + str(prefix / "include"), "-o", str(output)]
    if sys.platform == "darwin":
        command += ["-D_DARWIN_C_SOURCE"]
    if "#define BENCH_GC 1" in Path(source).read_text():
        command += ["-x", "none", str(prefix / "lib/libgc.a")]
    command += ["-lm"]
    proc = subprocess.run(command, capture_output=True, text=True, env=env)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return command


def verify(prefix, out):
    results = {}
    for variant in ("gc", "gc_atomic"):
        for optimization in ("0", "2", "3"):
            emitter = MemoryEmitter()
            emitter.variant, emitter.force_gc = variant, True
            source = BUILD / f"stress_{variant}_{optimization}.c"
            source.write_text(emitter.emit(check(parse(STRESS))))
            exe = source.with_suffix(".exe")
            compile_experiment(source, exe, prefix, optimization)
            proc = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
            assert proc.returncode == 0 and proc.stdout == STRESS_EXPECTED, (variant, optimization, proc.stdout, proc.stderr)
            results[f"stress/{variant}/O{optimization}"] = "passed; full collection before every allocation"
    # Reuse the original behavioral tests with experiment-only dependency injection.
    # CLI tests and GUI/system suites are intentionally not included.
    sys.path.insert(0, str(ROOT / "tests"))
    original_compile = backend.compile_c
    try:
        backend.Emitter = MemoryEmitter
        backend.compile_c = lambda source, output, optimization="2": compile_experiment(source, output, prefix, optimization)
        MemoryEmitter.variant, MemoryEmitter.force_gc = "gc_atomic", True
        names = ["test_records.RecordNativeTests", "test_reductions.ReductionTests"]
        names += ["test_systems.SystemsTests." + name for name in
                  ("test_text_and_unicode", "test_runtime_errors", "test_files_arguments_and_process")]
        names += ["test_glyph.NativeTests." + name for name in ("test_examples", "test_semantics", "test_runtime_traps", "test_random_arithmetic_differential")]
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        log = io.StringIO()
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        (out / "compatibility.log").write_text(log.getvalue())
        print(log.getvalue(), flush=True)
        assert result.wasSuccessful() and not result.skipped
        results["existing_native_tests"] = result.testsRun
    finally:
        backend.Emitter, backend.compile_c = BASE_EMITTER, original_compile
        MemoryEmitter.force_gc = False
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gc-prefix", type=Path, default=ROOT / "build/memory-deps/install")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--scales", type=int, nargs="+", default=[1, 4, 8])
    args = parser.parse_args()
    if "#define GLYPH_GC 1" in (ROOT / "glyph/runtime.h").read_text():
        parser.error("this historical comparison rewrites the former arena runtime; run it from the source-snapshot.tar.gz recorded in results/macos-arm64-2026-10-21-memory")
    if args.samples < 3 or any(s < 1 or s > 16 for s in args.scales):
        parser.error("at least 3 samples; scales must be 1..16")
    if os.name == "nt":
        parser.error("this experiment's RSS harness currently requires POSIX")
    if os.environ.get("GLYPH_SKIP_EXECUTION") == "1":
        parser.error("native execution must be enabled")
    prefix, out = args.gc_prefix.resolve(), args.output_dir.resolve()
    if not (prefix / "lib/libgc.a").exists():
        parser.error("build the pinned GC dependency first")
    BUILD.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    inputs = list((ROOT / "glyph").glob("*.py")) + list((ROOT / "glyph").glob("*.h"))
    inputs += list((ROOT / "tests").glob("test_*.py"))
    inputs += [Path(__file__), Path(__file__).with_name("memory_cases.py")]
    hashes = {str(p.resolve().relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    report = {
        "started_at": datetime.now(ZoneInfo("Europe/Vilnius")).isoformat(),
        "source_sha256": hashes, "samples": args.samples, "scales": args.scales,
        "metadata": {"os": platform.platform(), "python": sys.version,
                     "clang": subprocess.check_output(backend.compiler() + ["--version"], text=True).strip(),
                     "gc_version": GC_VERSION, "gc_archive_sha256": GC_ARCHIVE_SHA256,
                     "gc_library_sha256": hashlib.sha256((prefix / "lib/libgc.a").read_bytes()).hexdigest(),
                     "gc_configuration": "static; single-threaded; default stop-the-world collection; all interior pointers enabled; no GC heap limit; no forced collection in timed workloads",
                     "developer_dir": os.environ.get("DEVELOPER_DIR")},
        "method": "Fresh process per sample; one verified warmup; shuffled order; internal work+reclamation clock; OS process peak RSS; p99/max batch latency includes mutator and collector work, not isolated GC pauses; final explicit GC is outside timing and peak RSS sampling.",
        "region_scope": "Manual no-escape batch cleanup using existing allocation list. An idealized lifetime oracle, not a safe general-purpose language implementation. Retained workload excluded.",
        "not_tested": ["reference counting implementation", "precise custom GC", "incremental/concurrent GC", "GUI and foreign/native retained pointers", "other platforms", "hard real-time limits"],
        "variants": list(VARIANTS), "compatibility": verify(prefix, out), "compilation": {}, "runs": {},
    }
    commands = {}
    for task, case in CASES.items():
        for variant in VARIANTS:
            if variant == "region" and not case["region_eligible"]:
                continue
            emitter = MemoryEmitter()
            emitter.variant = variant
            text = emitter.emit(check(parse(case["source"])), task + ".gly")
            text = text[:text.index("int main(int argc, char **argv) {")]
            harness = HARNESS.replace("INIT", "GC_set_all_interior_pointers(1); GC_INIT();" if variant.startswith("gc") else "")
            harness = harness.replace("SETUP", "g_array keep = f_setup();" if task == "retained" else "")
            harness = harness.replace("WORK", "f_work(i, keep)" if task == "retained" else "f_work(i)")
            harness = harness.replace("VALIDATE", "f_validate(keep)" if task == "retained" else "0")
            harness = harness.replace("RELEASE", "region_end(mark);" if variant == "region" else "(void)mark;")
            source = BUILD / f"{task}_{variant}.c"
            source.write_text(text + harness)
            (out / f"{task}.gly").write_text(case["source"])
            exe = source.with_suffix(".exe")
            command = compile_experiment(source, exe, prefix)
            key = task + "/" + variant
            commands[key] = str(exe)
            report["compilation"][key] = {"command": command, "generated_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    def run(key, scale):
        n = 512 * scale
        start = time.perf_counter()
        proc = subprocess.run([commands[key], str(n)], capture_output=True, text=True, timeout=60, check=True)
        row = json.loads(proc.stdout)
        row["process_wall_s"] = time.perf_counter() - start
        task = key.split("/")[0]
        assert row["checksum"] == CASES[task]["expected"](n), (key, row)
        assert row["retained"] == (2 * sum(range(n - 32, n)) if task == "retained" else 0), (key, row)
        assert row["peak_rss_bytes"] > 0 and math.isfinite(row["elapsed_s"]) and row["elapsed_s"] > 0
        return row
    order = [(key, scale) for key in commands for scale in args.scales]
    for key, scale in order:
        run(key, scale)
        report["runs"][f"{key}/{scale}"] = {"batches": 512 * scale, "measurements": []}
    rng = random.Random(20261020)
    for trial in range(args.samples):
        rng.shuffle(order)
        for key, scale in order:
            report["runs"][f"{key}/{scale}"]["measurements"].append(run(key, scale))
        print("verified memory trial", trial + 1, flush=True)
    for data in report["runs"].values():
        data["medians"] = {field: statistics.median(row[field] for row in data["measurements"]) for field in data["measurements"][0]}
    report["source_changes_during_run"] = [path for path, digest in hashes.items()
                                          if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest]
    report["finished_at"] = datetime.now(ZoneInfo("Europe/Vilnius")).isoformat()
    (out / "memory.json").write_text(json.dumps(report, indent=2) + "\n")
    assert not report["source_changes_during_run"], report["source_changes_during_run"]
    for key, data in report["runs"].items():
        m = data["medians"]
        print(f"{key}: {m['elapsed_s'] * 1000:.3f} ms, {m['peak_rss_bytes']/1048576:.2f} MiB peak, batch p99 {m['batch_p99_s']*1000:.3f} ms")
    print("saved", out / "memory.json")


if __name__ == "__main__":
    main()
