"""Build a comparison from saved measurements; run after run.py."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent


def read(name, directory=OUT):
    return json.loads((directory / (name + ".json")).read_text())


runtime = read("runtime")
before = read("runtime", OUT.parent / "macos-arm64-2026-10-20")
reductions = read("reductions")
records = read("records")
memory = read("memory")
historical_memory = read("memory", OUT.parent / "macos-arm64-2026-10-21-memory")
verification = read("verification")
assert all(v == "passed" for v in verification["steps"].values())
assert not verification["source_changes_during_run"]

lines = ["# Production GC benchmark — 2026-10-21", "",
         "Measured the current working tree with the production bundled BDWGC collector and atomic allocation for pointer-free data. Compiler/runtime sources were unchanged during the run. The correctness suite passed 54 tests, including forced collection at O0/O2/O3, automatic reclamation and AppKit lifecycle tests; three self-hosted CLI tests were skipped because GLYPH_SELFHOST was not selected.", "",
         "Completed 390 checked timing samples: 150 standard runtime, 120 focused reduction, 60 record and 60 allocation samples, in addition to warmups. All nine scripted-repair fixtures and all six record inventory fixtures verified. Tests and benchmark suites ran sequentially.", "",
         "## Standard kernels: historical comparison", "",
         "Medians in milliseconds; earlier measurements are from October 20 (five samples), current measurements use 15. The same authored input hashes are checked below. This is a comparison between sessions, not an isolated causal measurement of GC overhead: compiler changes, machine load and clock variability can contribute. C is included as a contemporaneous reference.", "",
         "| Kernel | Earlier Glyph | Current Glyph | Change | Earlier C | Current C | Current Glyph/C |",
         "|---|---:|---:|---:|---:|---:|---:|"]
for task in ("array", "array_loop", "recurrence"):
    key = task + "/glyph"
    ck = ("array" if task == "array_loop" else task) + "/c"
    old = before["runs"][key]["kernel_s"]["median"]
    new = runtime["runs"][key]["kernel_s"]["median"]
    oc = before["runs"][ck]["kernel_s"]["median"]
    nc = runtime["runs"][ck]["kernel_s"]["median"]
    assert runtime["source_sha256"][key] == before["source_sha256"][key]
    lines.append(f"| {task} | {old*1000:.3f} | {new*1000:.3f} | {(new/old-1)*100:+.1f}% | {oc*1000:.3f} | {nc*1000:.3f} | {new/nc:.2f}× |")
lines += ["", "Glyph kernel medians rose 33–35% since the earlier session, while the corresponding C medians rose 35–37%. Relative performance is therefore broadly similar; these observations do not isolate a GC-induced kernel regression. Record medians remain within 2% of C in this run, with overlapping ranges.", "",
          "Kernel timing excludes startup and allocation/setup. These bounded-allocation workloads primarily test whether GC integration disturbed computation performance.", "",
          "## Startup and executable size", "",
          "| Metric | Earlier Glyph | Current Glyph | Current C |", "|---|---:|---:|---:|"]
for label, fn, fmt in (
    ("Empty process median (ms)", lambda d,k: d["runs"][k]["wall_s"]["median"]*1000, ".3f"),
    ("Empty executable (bytes)", lambda d,k: d["compilation"][k]["artifact_bytes"], ",d"),
    ("Warm empty-program compilation (ms)", lambda d,k: d["compilation"][k]["median_warm_s"]*1000, ".3f"),
):
    values = [fn(before,"startup/glyph"), fn(runtime,"startup/glyph"), fn(runtime,"startup/c")]
    lines.append("| " + label + " | " + " | ".join(format(v,fmt) for v in values) + " |")
lines += ["", "Process times include the polling harness; short-lived processes and uncontrolled load make small startup differences noisy. Binary sizes include the statically linked collector. Compilation uses the existing collector/compiler caches; this is not a cold-build measurement.", "",
          "## Focused reductions and records", "",
          "15 samples per variant, internal kernel time, one checked warmup and shuffled process order. No process-memory polling in these suites.", "",
          "| Reduction | Fold (ms) | Builtin sum (ms) | Checked loop (ms) | C (ms) |", "|---|---:|---:|---:|---:|"]
for scenario in ("small", "wide"):
    lines.append("| " + scenario + " | " + " | ".join(f'{reductions["runs"][scenario+"/"+variant]["median_s"]*1000:.3f}' for variant in ("fold","sum","loop","c")) + " |")
lines += ["", "| Record workload | Glyph median (range), ms | C median (range), ms | Glyph/C |", "|---|---:|---:|---:|"]
for task in ("point", "particle"):
    g,c = (records["runs"][task+"/"+lang] for lang in ("glyph","c"))
    def timing(d):
        return f'{d["median_s"]*1000:.3f} ({d["min_s"]*1000:.3f}–{d["max_s"]*1000:.3f})'
    lines.append(f'| {task} | {timing(g)} | {timing(c)} | {g["median_s"]/c["median_s"]:.3f}× |')
lines += ["", "## Allocation-heavy workloads", "",
          "Five fresh processes per workload at 512, 2,048 and 4,096 batches (60 measured processes). The table shows 4,096-batch medians. Generated Glyph functions and production allocator are unchanged; a C driver measures work plus automatic collection. OS peak RSS comes from getrusage, not polling. Batch p99 includes mutator work and collection; it is not an isolated GC pause. A final explicit collection happens after timing and peak-RSS capture.", "",
          "| Workload | Current elapsed (ms) | Current peak RSS (MiB) | Historical arena peak (MiB) | Current heap capacity (MiB) | Batch p99 (ms) | Collections |", "|---|---:|---:|---:|---:|---:|---:|"]
for task in ("numeric", "text", "cycles", "retained"):
    m = memory["runs"][task+"/8"]["medians"]
    old = historical_memory["runs"][task+"/arena/8"]["medians"]
    lines.append(f'| {task} | {m["elapsed_s"]*1000:.3f} | {m["peak_rss_bytes"]/2**20:.2f} | {old["peak_rss_bytes"]/2**20:.2f} | {m["gc_heap_bytes"]/2**20:.3f} | {m["batch_p99_s"]*1000:.3f} | {m["gc_collections"]:g} |')
lines += ["", "The arena column is historical context from the earlier allocator experiment, not a rerun of arena on this compiler. That experiment used allocator instrumentation and a separately built collector; timing differences from it cannot be attributed solely to production integration. Current raw data includes all scales, checksums, retained-value validation, cumulative collector allocation bytes, and heap capacity. Heap capacity is distinct from process RSS.", "",
          "## Evidence and reproduction", "",
          "[Full runtime/token report](REPORT.md) · [runtime](runtime.json) · [reductions](reductions.json) · [records](records.json) · [memory](memory.json) · [test log](tests.log) · [provenance and source hashes](verification.json) · [frozen sources](source-snapshot.tar.gz).", "",
          "Source-token counts describe authored fixtures. Actual model retries, reasoning and billed task costs were not measured. No machine-load isolation or cross-platform performance measurement was performed.", "",
          "From the repository root, with process inspection permitted and benchmark dependencies installed:", "", "```sh",
          "GLYPH_TEST_GUI=1 DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python benchmarks/results/macos-arm64-2026-10-21-post-gc/run.py",
          ".venv/bin/python benchmarks/results/macos-arm64-2026-10-21-post-gc/summarize.py", "```", "",
          "Use a copy of this output directory for a future run to preserve these observations. The frozen source archive includes the runner at its repository-relative path; extract it into a separate checkout before reproducing this exact snapshot."]
(OUT / "COMPARISON.md").write_text("\n".join(lines) + "\n")
path = OUT / "REPORT.md"
path.write_text(path.read_text().replace("the arena retention tradeoff is not exercised by these bounded-allocation kernels", "GC reclamation behavior is measured separately in [the allocation workloads](COMPARISON.md#allocation-heavy-workloads)").replace("[../README.md](../README.md)", "[methodology](../../README.md)"))
print(OUT / "COMPARISON.md")
