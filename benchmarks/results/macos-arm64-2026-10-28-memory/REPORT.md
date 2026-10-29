# Memory and compiler improvements — 2026-10-28

Starting commit: `5595ee6b99164897fb50e28772c4be755f2a9461`. The pre-existing `.DS_Store` change and subsequently appearing `examples/.DS_Store` were preserved.

Host: Apple M2, 8 physical/8 logical cores, 8 GiB RAM, `macOS-26.5.2-arm64-arm-64bit-Mach-O`. Python 3.14.7, Zig 0.14.1. Exact compiler versions, flags and environment are in [baseline metadata](baseline/metadata.json).

## What shipped

Both frontends implement checked `@noalloc`, primitive scoped arenas, affine local owned buffers with move/free and unique scoped borrowing, bounded stack arrays/scalar closure environments, direct local-closure calls, alias-checked fill-buffer reuse, immediate construction/reduction fusion, narrow check proofs and removal of redundant pointer-free initialization. PGO/LTO/native-target flags preserve checked arithmetic and floating-point flags. Allocation/GC-event instrumentation is opt-in. BDWGC remains the default nonmoving collector. See [language contracts](../../../docs/MEMORY_CONTROLS.md) and [release workflow](../../../docs/RELEASE_OPTIMIZATION.md).

## Correctness and reproducibility

- Baseline: 123 tests, six skips. Final reference run: 132 tests, three skips (live GUI and two Linux `/dev/full` cases), no failures. The native differential corpus reports its exact check/emission counts in [the native log](native-tests.log); the memory-control tests additionally exercise both compilers at O0/O1/O2/O3 and under GC stress.
- Three-stage bootstrap fixed point verified; stage 2 and stage 3 C match byte for byte. [Bootstrap evidence](bootstrap/verification.json).
- Negative tests cover aliases, closures, generic contracts, unknown callbacks, recursion, region/borrow escape, unsupported reference layouts, use after move/free, double-free, outer-owner consumption and unreachable region blocks. Disjoint lexical names cannot be conflated by optimization proofs.
- UBSan passes explicit storage and GC-root/slice/cycle/pointer workloads. ASan aborts during sanitizer initialization and TSan segfaults even for an empty C `main`; their checks are unavailable on this host, not claimed as passes. [Exact commands and minimal probes](validation/results.json). Explicit malloc-failure injection produces R004 for both domains.
- Both standalone drivers also build/run the memory example using profile generation/use, thin LTO and native CPU flags. [Driver checks](validation/driver-release.json).
- The final matrix uses file-based loading and subprocess frontend invocation for both baseline and current reference variants. Preliminary observations with mismatched file-location metadata are retained in `preliminary-results.tar.gz` and are superseded. They are not used in the tables below.

## Paired workload results

Seven uninstrumented process trials after one warmup per case; deterministic randomized order. Internal work intervals include the allocations being studied. Setup is separately clocked, and whole-process wall time includes startup/output/cleanup. No correctness suites or other benchmark suites ran concurrently with the final timing matrix. Values below are medians; brackets contain observed minima and maxima. They are not confidence intervals.

| Workload | Baseline ms [range] | Combined ms [range] | Change | GC allocation requests, baseline → combined |
|---|---:|---:|---:|---:|
| temporary | 2.005 [1.981, 2.259] | 0.594 [0.592, 0.608] | -70.4% | 30,000 → 0 |
| closure | 0.806 [0.776, 0.842] | 0.085 [0.085, 0.086] | -89.5% | 200,000 → 0 |
| escaping | 2.045 [1.975, 2.098] | 2.011 [1.987, 2.071] | -1.7% | 30,000 → 30,000 |
| fusion | 1.989 [1.981, 2.248] | 0.719 [0.711, 0.723] | -63.9% | 30,000 → 0 |
| checks | 1.543 [1.520, 1.598] | 0.188 [0.187, 0.216] | -87.8% | 300,000 → 0 |
| numeric | 14.255 [13.997, 15.641] | 13.244 [13.004, 15.396] | -7.1% | 6,000 → 6,000 |
| cycles | 3.269 [3.240, 3.354] | 3.286 [3.255, 3.350] | +0.5% | 576,000 → 576,000 |
| text | 5.835 [5.737, 5.953] | 5.871 [5.782, 6.603] | +0.6% | 65,000 → 65,000 |
| retained_slices | 1.757 [1.746, 1.763] | 1.798 [1.752, 1.848] | +2.3% | 60,033 → 60,033 |
| reuse | 4.898 [4.716, 5.402] | 0.899 [0.896, 0.970] | -81.6% | 10,001 → 1 |

Allocation elimination helps the eligible temporary/closure/fusion/reuse kernels. Escaping arrays, cyclic graphs, string allocation and retained slices remain on the managed path; small changes there should not be interpreted as universal improvements. Check elimination alone provides little benefit in these kernels because LLVM already removes many checks.

### Independent transformations

Ablations use the current runtime with frontend transformations disabled and zeroing restored as their control. This separates each transformation from baseline-to-current runtime/code-generation differences.

| Workload / feature | Current unoptimized ms | Feature alone ms | Combined ms |
|---|---:|---:|---:|
| temporary / stack | 2.003 | 0.597 | 0.594 |
| closure / stack | 0.777 | 0.086 | 0.085 |
| reuse / reuse | 4.910 | 0.902 | 0.899 |
| fusion / fusion | 2.000 | 0.720 | 0.719 |
| numeric / init | 14.352 | 13.463 | 13.244 |
| checks / checks | 1.557 | 1.528 | 0.188 |

Stack/closure ablation includes direct local-closure targeting. The init ablation restores zeroing in the control, including runtime clone/range helpers. The full raw matrix includes all features on every ordinary workload, so unsuccessful and potentially regressing cases remain visible.

### Explicit domains

| Variant, same 30,000 × 64-element fill/reduction workload | Work ms | GC / arena / owned requests | Peak RSS MiB |
|---|---:|---:|---:|
| temporary/baseline | 2.005 | 30,000 / 0 / 0 | 2.42 |
| temporary/combined | 0.594 | 0 / 0 / 0 | 1.95 |
| arena/combined | 3.374 | 0 / 30,000 / 0 | 1.98 |
| owned/combined | 1.253 | 0 / 0 / 30,000 | 1.97 |

The arena case creates/releases an arena per function call; chunk setup dominates this small allocation. It demonstrates a regression, not a recommended arena batching strategy. Owned malloc/free is explicit and bounded by scope, but stack promotion is faster for this eligible workload. These source variants have different lifetime-management operations; they are not automatic transformations of the baseline program.

### Parallel allocation

| Workers | Baseline ms | Combined ms | Million callbacks/s, baseline → combined | Baseline requests | Combined requests |
|---:|---:|---:|---:|---:|---:|
| 1 | 114.791 | 61.099 | 4.36 → 8.18 | 500,006 | 6 |
| 2 | 98.445 | 32.026 | 5.08 → 15.61 | 500,006 | 6 |
| 4 | 118.820 | 17.008 | 4.21 → 29.40 | 500,006 | 6 |

Each trial maps 100,000 elements five times, with 128-element temporary callback arrays. One-worker mode uses the same threaded binary/collector. Output-array allocations remain. [A separate statistical profile](profile/baseline-parallel.txt) samples `GC_malloc_kind_global` and `GC_lock` in the baseline; it is excluded from timing results.

## Memory and GC observations

The raw matrix retains an uninstrumented `/usr/bin/time -l` peak-RSS control and a separate counter/GC-hook run for every variant. Counter overhead is therefore observable rather than mixed into the primary timings. Each control is one process; it is not a repeated estimate of instrumentation overhead.

| Case | Peak RSS MiB, baseline → combined | Final GC capacity KiB, baseline → combined | Requested GC bytes, baseline → combined |
|---|---:|---:|---:|
| temporary | 2.42 → 1.95 | 256.0 → 256.0 | 15,360,000 → 0 |
| closure | 2.45 → 1.95 | 256.0 → 256.0 | 1,600,000 → 0 |
| numeric | 2.67 → 2.69 | 512.0 → 512.0 | 196,608,000 → 196,608,000 |
| reuse | 2.70 → 1.98 | 512.0 → 256.0 | 40,964,096 → 4,096 |
| retained_slices | 2.44 → 2.44 | 256.0 → 256.0 | 488,484 → 488,484 |
| cycles | 2.44 → 2.42 | 256.0 → 256.0 | 13,824,000 → 13,824,000 |

Final capacity minus free bytes is occupied collector capacity, not precise reachable/retained bytes. Arena request bytes exclude chunk overhead; owned/arena capacity is reflected only in process RSS. There is no claim of exact live-byte accounting for the conservative collector.

| Instrumented case | Collection events | Collector-thread CPU ms | Stop-world p50 / p95 / max ms |
|---|---:|---:|---:|
| numeric/baseline/1 | 500 | 24.383 | unobserved |
| numeric/combined/1 | 500 | 20.925 | unobserved |
| parallel/baseline/4 | 457 | 23.023 | 0.022 / 0.031 / 0.055 |
| parallel/combined/4 | 4 | 0.172 | 0.026 / 0.026 / 0.034 |
| retained_slices/baseline/1 | 3 | 0.087 | unobserved |

These are collector event intervals, not batch latency. The sequential collector does not emit the stop/start-world events used here, so its pause samples are unavailable even when collection events are counted. Stop-world samples exclude suspension/resumption. Hooks are installed after GC initialization; startup collections are not timed. Samples cap at 4096; total counts expose truncation. Collector-thread CPU excludes other threads.

## Startup and compilation

Empty-process wall medians: 2.721 ms baseline, 2.762 ms combined (+1.5%). This is process startup, not kernel time.

| Self-hosted compiler, same frozen compiler input | Median emit-C wall ms [range] | Executable bytes | Peak RSS MiB | GC requests / requested MiB |
|---|---:|---:|---:|---:|---:|
| baseline | 291.440 [280.639, 346.684] | 480,056 | 176.36 | 6,894,587 / 271.94 |
| combined | 298.075 [297.041, 311.264] | 513,432 | 192.64 | 7,110,696 / 287.55 |

The real compiler workload includes startup, module loading, checking, analysis and C emission. Additional analysis may regress this workload. The build table in the raw matrix records frontend process time, C backend time, executable sizes, commands and hashes for every case. Those build timings have one sample per case and uncontrolled warm caches; release comparisons below include two build samples per variant.

## PGO, LTO and CPU targeting

Training/evaluation inputs and profiles are separate. Both frontends are tested; compiler evaluation emits the same frozen source and verifies byte-identical outputs across release variants. Application C is profiled/LTO-optimized; the separately cached BDWGC object is not. Portable builds remain available.

| Native-emitted compiler variant | Held-out wall ms | Build seconds (two samples) | Executable bytes |
|---|---:|---:|---:|
| portable | 303.806 | 2.477, 2.473 | 513,400 |
| thin_lto | 299.165 | 3.179, 3.187 | 463,448 |
| full_lto | 305.683 | 2.915, 2.916 | 463,544 |
| native_cpu | 304.645 | 2.472, 2.546 | 513,400 |
| pgo | 296.989 | 2.129, 2.123 | 488,512 |
| pgo_thin_lto | 286.707 | 2.773, 2.754 | 415,296 |

See [native compiler release results](release/native-compiler/results.json), [reference compiler results](release/reference-compiler/results.json), and the [reference](release/reference-array/results.json)/[native](release/native-array/results.json) array evaluations. PGO/LTO can help the compiler while providing little benefit or a small regression on the reduction kernel. No global release speedup is claimed.

## Collector experiments and decisions

| Shared BDWGC allocator | 1 worker ms | 2 workers ms | 4 workers ms |
|---|---:|---:|---:|
| global | 116.948 | 98.358 | 116.747 |
| thread_local | 102.232 | 164.753 | 176.991 |

Thread-local allocation caches retain one shared collector and registered stacks, so this experiment does not weaken publication or pointer guarantees. They regressed multithreaded allocation in this workload and are not enabled. [Raw experiment](allocator/results.json).

The isolated explicit-root/layout collector took 5.333 ms versus 15.668 ms for the forced-collection cycle microbenchmark. It is nonmoving and tests an interior root, cyclic edges and complete reclamation. Both variants collect after each 256 nodes. This tiny explicit-root graph is favorable to the prototype and is not an application/backend comparison. [Source](../../../benchmarks/precise_gc.h) and [raw samples](precise/results.json).

Not implemented as language backends: precise collection, worker-local collection, or moving/generational collection. The prototype has no compiler-emitted root stack, runtime/service root ABI, published-value protocol, safepoints, write barriers or pinning policy. Integrating any replacement without these would be unsound for strings, channels, escaping results and stable/interior pointers. These are deferred architectural work, not simultaneously shipped strategies.

## Remaining limits

- Explicit storage supports primitive elements and local owners only. Cross-function ownership transfer, reference-bearing layouts and worker use are rejected. No hidden managed references are allowed in malloc storage.
- Analysis is conservative, with a small audited use grammar. General interprocedural escape precision, dynamic induction-range proofs and arbitrary callback fusion are not implemented. Native reports are narrower than reference reports.
- No Windows/Linux run, GUI interaction run, functioning ASan/TSan run, precise live-byte accounting, power/affinity control or statistical confidence interval is claimed.
- Input choices are bounded kernels and one compiler workload, not a representative application population. Read raw ranges and regressions before generalizing.

## Reproduce

```sh
mkdir -p build/memory-baseline
tar -xf benchmarks/results/macos-arm64-2026-10-28-memory/baseline/source.tar.gz -C build/memory-baseline
# Bootstrap the frozen compiler from its own working directory:
(cd build/memory-baseline && DEVELOPER_DIR=/Library/Developer/CommandLineTools ../../.venv/bin/python selfhost/bootstrap.py)
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python selfhost/bootstrap.py --output-dir build/memory-selfhost
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m unittest discover -s tests -v
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python selfhost/verify.py build/memory-selfhost/glyphc
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m benchmarks.memory_suite --baseline build/memory-baseline --samples 7
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m benchmarks.memory_validation
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m benchmarks.compiler_memory_measurements
.venv/bin/python -m benchmarks.memory_profile
.venv/bin/python -m benchmarks.memory_report
.venv/bin/python -m benchmarks.memory_delivery
```

OS process inspection/local socket tests may require running outside a restricted sandbox. Full baseline/current runtime, reduction, record and concurrency suite results are retained alongside [the paired matrix](comparison/results.json). The baseline archive plus `implementation-overlay.tar.gz` reconstruct the sources. `release/profiles-and-c.tar.gz` preserves generated C and raw/merged profiles, and `manifest.json` records file hashes; `preliminary-results.tar.gz` is explicitly superseded.
