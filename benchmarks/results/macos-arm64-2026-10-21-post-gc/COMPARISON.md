# Production GC benchmark — 2026-10-21

Measured the current working tree with the production bundled BDWGC collector and atomic allocation for pointer-free data. Compiler/runtime sources were unchanged during the run. The correctness suite passed 54 tests, including forced collection at O0/O2/O3, automatic reclamation and AppKit lifecycle tests; three self-hosted CLI tests were skipped because GLYPH_SELFHOST was not selected.

Completed 390 checked timing samples: 150 standard runtime, 120 focused reduction, 60 record and 60 allocation samples, in addition to warmups. All nine scripted-repair fixtures and all six record inventory fixtures verified. Tests and benchmark suites ran sequentially.

## Standard kernels: historical comparison

Medians in milliseconds; earlier measurements are from October 20 (five samples), current measurements use 15. The same authored input hashes are checked below. This is a comparison between sessions, not an isolated causal measurement of GC overhead: compiler changes, machine load and clock variability can contribute. C is included as a contemporaneous reference.

| Kernel | Earlier Glyph | Current Glyph | Change | Earlier C | Current C | Current Glyph/C |
|---|---:|---:|---:|---:|---:|---:|
| array | 2.539 | 3.390 | +33.5% | 1.852 | 2.533 | 1.34× |
| array_loop | 6.705 | 9.050 | +35.0% | 1.852 | 2.533 | 3.57× |
| recurrence | 4.164 | 5.528 | +32.8% | 4.116 | 5.548 | 1.00× |

Glyph kernel medians rose 33–35% since the earlier session, while the corresponding C medians rose 35–37%. Relative performance is therefore broadly similar; these observations do not isolate a GC-induced kernel regression. Record medians remain within 2% of C in this run, with overlapping ranges.

Kernel timing excludes startup and allocation/setup. These bounded-allocation workloads primarily test whether GC integration disturbed computation performance.

## Startup and executable size

| Metric | Earlier Glyph | Current Glyph | Current C |
|---|---:|---:|---:|
| Empty process median (ms) | 5.424 | 6.898 | 6.856 |
| Empty executable (bytes) | 50,000 | 98,032 | 49,944 |
| Warm empty-program compilation (ms) | 119.923 | 256.624 | 98.946 |

Process times include the polling harness; short-lived processes and uncontrolled load make small startup differences noisy. Binary sizes include the statically linked collector. Compilation uses the existing collector/compiler caches; this is not a cold-build measurement.

## Focused reductions and records

15 samples per variant, internal kernel time, one checked warmup and shuffled process order. No process-memory polling in these suites.

| Reduction | Fold (ms) | Builtin sum (ms) | Checked loop (ms) | C (ms) |
|---|---:|---:|---:|---:|
| small | 3.089 | 3.062 | 8.224 | 2.334 |
| wide | 8.552 | 8.244 | 8.327 | 2.356 |

| Record workload | Glyph median (range), ms | C median (range), ms | Glyph/C |
|---|---:|---:|---:|
| point | 7.523 (7.146–24.850) | 7.647 (7.513–8.057) | 0.984× |
| particle | 7.768 (7.137–10.870) | 7.766 (7.480–9.516) | 1.000× |

## Allocation-heavy workloads

Five fresh processes per workload at 512, 2,048 and 4,096 batches (60 measured processes). The table shows 4,096-batch medians. Generated Glyph functions and production allocator are unchanged; a C driver measures work plus automatic collection. OS peak RSS comes from getrusage, not polling. Batch p99 includes mutator work and collection; it is not an isolated GC pause. A final explicit collection happens after timing and peak-RSS capture.

| Workload | Current elapsed (ms) | Current peak RSS (MiB) | Historical arena peak (MiB) | Current heap capacity (MiB) | Batch p99 (ms) | Collections |
|---|---:|---:|---:|---:|---:|---:|
| numeric | 31.222 | 2.70 | 258.47 | 0.500 | 0.035 | 684 |
| text | 34.631 | 2.45 | 151.83 | 0.250 | 0.031 | 878 |
| cycles | 6.791 | 2.45 | 37.48 | 0.250 | 0.023 | 97 |
| retained | 15.238 | 3.64 | 130.17 | 1.438 | 0.027 | 512 |

The arena column is historical context from the earlier allocator experiment, not a rerun of arena on this compiler. That experiment used allocator instrumentation and a separately built collector; timing differences from it cannot be attributed solely to production integration. Current raw data includes all scales, checksums, retained-value validation, cumulative collector allocation bytes, and heap capacity. Heap capacity is distinct from process RSS.

## Evidence and reproduction

[Full runtime/token report](REPORT.md) · [runtime](runtime.json) · [reductions](reductions.json) · [records](records.json) · [memory](memory.json) · [test log](tests.log) · [provenance and source hashes](verification.json) · [frozen sources](source-snapshot.tar.gz).

Source-token counts describe authored fixtures. Actual model retries, reasoning and billed task costs were not measured. No machine-load isolation or cross-platform performance measurement was performed.

From the repository root, with process inspection permitted and benchmark dependencies installed:

```sh
GLYPH_TEST_GUI=1 DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python benchmarks/results/macos-arm64-2026-10-21-post-gc/run.py
.venv/bin/python benchmarks/results/macos-arm64-2026-10-21-post-gc/summarize.py
```

Use a copy of this output directory for a future run to preserve these observations. The frozen source archive includes the runner at its repository-relative path; extract it into a separate checkout before reproducing this exact snapshot.
