# Production GC benchmark rerun — 2026-10-21

Completed 390 verified timing samples: 150 runtime, 120 reductions, 60 records, 60 memory. Warmups are additional.

Correctness: 68 tests passed; 4 skipped (three self-hosted CLI tests because GLYPH_SELFHOST was not selected, and one write-failure test requiring /dev/full, unavailable on macOS). The AppKit lifecycle and forced-GC tests ran. Compiler/runtime source hashes remained unchanged throughout this run.

Run: 2026-10-21T23:07:46.854737+03:00 to 2026-10-21T23:09:10.084176+03:00 (Europe/Vilnius).

The current compiler includes changes since the first production-GC run, including collection/result support. These are separate working-tree snapshots with uncontrolled host load; differences cannot be attributed solely to GC or to a particular compiler change. Suites ran sequentially. Both runs use 15 samples per standard runtime, reduction and record case, plus five samples per allocation workload/scale.

## Kernel comparison

Median milliseconds; negative change means faster. The benchmark input source hashes match between runs.

| Case | Previous | Rerun | Change |
|---|---:|---:|---:|
| array/glyph | 3.390 | 2.405 | -29.1% |
| array/c | 2.533 | 1.805 | -28.7% |
| array/python | 115.939 | 80.664 | -30.4% |
| array_loop/glyph | 9.050 | 6.382 | -29.5% |
| recurrence/glyph | 5.528 | 3.974 | -28.1% |
| recurrence/c | 5.548 | 3.932 | -29.1% |
| recurrence/python | 138.667 | 92.608 | -33.2% |

Kernel clocks exclude startup and setup/allocation; ordinary C omits Glyph's checked arithmetic. External process times and memory polling are preserved in the full report.

## Focused kernels

| Reduction | Fold (ms) | Sum (ms) | Checked loop (ms) | C (ms) |
|---|---:|---:|---:|---:|
| small | 2.259 | 2.245 | 6.157 | 1.710 |
| wide | 6.101 | 6.145 | 6.227 | 1.713 |

| Records | Glyph (ms) | C (ms) | Glyph/C |
|---|---:|---:|---:|
| point | 5.253 | 5.187 | 1.013× |
| particle | 5.269 | 5.282 | 0.998× |

## Allocation workloads

4,096-batch medians. getrusage measures whole-process peak RSS. Batch p99 includes mutator and collector work, not isolated GC pauses. All three scales (512/2,048/4,096 batches) and retained-value checks are in memory.json. No forced collection occurs within timing.

| Workload | Previous ms | Rerun ms | Previous peak MiB | Rerun peak MiB | Heap capacity MiB | Batch p99 ms |
|---|---:|---:|---:|---:|---:|---:|
| numeric | 31.222 | 21.550 | 2.70 | 2.70 | 0.500 | 0.022 |
| text | 34.631 | 24.358 | 2.45 | 2.47 | 0.250 | 0.021 |
| cycles | 6.791 | 4.559 | 2.45 | 2.45 | 0.250 | 0.017 |
| retained | 15.238 | 10.716 | 3.64 | 3.66 | 1.438 | 0.020 |

## Startup and size

| Metric | Previous Glyph | Rerun Glyph | Rerun C |
|---|---:|---:|---:|
| Empty process median (ms) | 6.898 | 6.237 | 6.170 |
| Empty executable (bytes) | 98,032 | 98,032 | 49,944 |
| Warm empty-program compile (ms) | 256.624 | 157.297 | 67.249 |

Short process times include polling overhead. Compiler and collector caches were reused; these are not cold builds. No CPU affinity, power or load controls were applied.

## Provenance

Changed previously recorded sources: `docs/AGENT_GUIDE.md`, `glyph/backend.py`, `glyph/checker.py`, `glyph/modules.py`, `glyph/std_runtime.h`, `glyph/stdlib.py`, `glyph/syntax.py`, `tests/test_glyph.py`.

New recorded sources: `glyph/collections.py`, `glyph/collections_runtime.h`, `tests/test_collections.py`, `tests/test_results.py`.

[Full runtime/token report](REPORT.md) · [runtime](runtime.json) · [reductions](reductions.json) · [records](records.json) · [allocation measurements](memory.json) · [tests](tests.log) · [source hashes](verification.json) · [frozen sources](source-snapshot.tar.gz).

Source-token inventories measure authored fixtures, not actual AI reasoning, retries or billed task costs.

Reproduce from the project root (copy the output directory first to preserve this run):

```sh
GLYPH_TEST_GUI=1 DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python benchmarks/results/macos-arm64-2026-10-21-post-gc-rerun-2/run.py
.venv/bin/python benchmarks/results/macos-arm64-2026-10-21-post-gc-rerun-2/summarize.py
```
