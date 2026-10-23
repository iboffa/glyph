# Memory-management experiment — 2026-10-21

**Recommendation: pursue a nonmoving tracing GC, using pointer-free allocations for numeric buffers and text.** This was the strongest general-purpose candidate tested. Keep scoped batch cleanup as a possible later optimization where lifetimes can be proved. The production allocator is unchanged; the prototype lives entirely in the benchmark code.

This is a selection among the tested implementations, not a comparison against every possible memory manager. Automatic reference counting, a custom precise collector, incremental collection and concurrent collection were not implemented or measured.

## Results

Five fresh measured processes per combination, following one verified warmup. Four workloads, three sizes (512, 2,048 and 4,096 batches), and four allocator variants, except that scoped cleanup is excluded when values escape. All **225 measured outputs** and 45 warmups matched independent checksums. Every retained buffer and string slice was also validated after the work completed.

At 4,096 batches, median process peak resident memory:

| Workload | Current allocator | Scoped batch cleanup | Plain GC | GC with pointer-free buffers |
|---|---:|---:|---:|---:|
| Temporary numeric arrays | 258.47 MiB | 1.41 MiB | 2.11 MiB | 2.11 MiB |
| Repeated string concatenation | 151.83 MiB | 1.69 MiB | 2.08 MiB | 2.08 MiB |
| Unreachable cyclic records | 37.48 MiB | 1.33 MiB | 1.92 MiB | 1.92 MiB |
| Buffers and slices retained across batches | 130.17 MiB | Ineligible | 4.09 MiB | 3.48 MiB |

Median measured work time at the same size:

| Workload | Current allocator | Scoped batch cleanup | Plain GC | GC with pointer-free buffers |
|---|---:|---:|---:|---:|
| Temporary numeric arrays | 86.27 ms | 19.42 ms | 68.13 ms | 57.69 ms |
| Repeated string concatenation | 50.88 ms | 30.10 ms | 50.51 ms | 45.09 ms |
| Unreachable cyclic records | 36.19 ms | 61.69 ms | 11.73 ms | 11.16 ms |
| Buffers and slices retained across batches | 19.72 ms | Ineligible | 27.74 ms | 14.62 ms |

Both GC variants maintained approximately stable peak memory as batch count grew eightfold. The current allocator's memory rose with cumulative allocation. Plain GC was slower than the current allocator in the retained-values case; marking numeric/text allocations as pointer-free improved both its time and memory there. The optimized GC had lower median time than the current allocator in all four largest cases, but this is not a guarantee of universal speedup. Reusing memory and a different small-object allocator can offset collection costs on these workloads.

Scoped cleanup was fastest for temporary arrays and strings. Its cycle case was slower than GC: this prototype individually frees the current allocator's linked list, rather than implementing a tuned bump allocator. It also relies on a manually verified fact that no allocation escapes a batch. It would invalidate retained values, so that combination is deliberately excluded. These measurements establish a useful lifetime-based alternative, not a safe automatic region implementation for the language.

## Latency

Median per-process 99th-percentile batch time, for the optimized GC at the largest size, was about 67 µs (numeric), 55 µs (text), 26 µs (cycles), and 39 µs (retained values).

These are **whole batch latencies**, including application work, collection and scheduling. They are not isolated collector pause durations. Across all five largest-case processes, maximum observed batches reached 9.71 ms for numeric and 12.66 ms for retained values. The experiment cannot attribute those outliers to GC versus scheduling or background load. It provides no hard real-time guarantee; interactive latency needs a dedicated follow-up before production adoption.

## Correctness and implementation

The dependency is Boehm–Demers–Weiser GC **8.2.12**, built locally as a static, single-threaded library. Interior pointers are enabled. Default stop-the-world collection policy is used with no configured heap cap; timed workloads do not force collections. The `gc_atomic` label means that allocations contain no pointers, not that operations are thread-safe.

The experiment replaces the generated C allocator without modifying the production frontend/runtime. GC allocations are not inserted into Glyph's global allocation list, which otherwise would keep them reachable forever. Record values remain inline. Numeric/Boolean buffers and records containing only pointer-free inline fields use `GC_malloc_atomic`; text storage does likewise. Buffers containing strings, array descriptors, pointers or records with such fields remain traced. Atomic allocations are explicitly zeroed to preserve the existing allocation contract. The collector's allocation interfaces are documented [here](https://www.hboehm.info/gc/gcinterface.html).

Six targeted stress executions passed: both GC variants at `-O0`, `-O2` and `-O3`, with a full collection forced **before every allocation**. These check heap-held interior string slices, heap-held raw interior pointers, one-past pointers subsequently moved back in bounds, reachable cyclic record arrays, shared aliases, and independent clones after allocation churn.

Another **16 existing native test methods** passed with the optimized GC and forced collection. These cover records, reductions, arithmetic, evaluation order, runtime diagnostics, examples, Unicode/text, file operations and child-process arguments. Some existing fixtures also compile at multiple optimization levels. See [the compatibility log](compatibility.log). GUI, native code retaining Glyph pointers, other execution platforms and the self-hosted compiler were not verified under GC in this run.

## Method and provenance

The host was macOS arm64, with Zig 0.14.1 / Clang 19.1.7 for all experiment executables. All variants use `-O2 -fno-fast-math -ffp-contract=off`. GC itself was built with the installed Apple toolchain. The existing Command Line Tools SDK selection was used for native linking.

Workloads are saved alongside this report:

- [numeric.gly](numeric.gly): fill and clone 4,096-element arrays; mutate the clone and verify both sums.
- [text.gly](text.gly): concatenate 64 fixed chunks onto a seed string, then check length and final byte.
- [cycles.gly](cycles.gly): build 64 two-node cycles per batch, traverse them, and discard them.
- [retained.gly](retained.gly): replace one of 32 retained records each batch; retain a numeric buffer and an interior string slice, then validate the final retained values.

Process order is deterministically shuffled each round. Internal work timing includes batch work and any in-loop reclamation. The current allocator defers its cleanup until process exit; that exit cleanup is excluded from the kernel time. Scoped cleanup is inside each batch. OS `getrusage` records process peak RSS, including setup, runtime and library overhead. There is no external process polling. Batch timing adds two clock reads per batch to every variant.

A final diagnostic full collection occurs after the timed region and peak-RSS read. Its heap/free-byte statistics are recorded separately. Whole-process wall times in the raw data include this diagnostic collection, startup and exit cleanup and should not be treated as isolated allocator throughput. There are no CPU-affinity, power-management or background-load controls.

An earlier run passed correctness and outputs but was rejected because module source changed during measurement. The accepted run used a frozen source copy and reports no source changes. [memory.json](memory.json) contains all samples, source hashes, compiler commands, checksums and collection counts. [source-snapshot.tar.gz](source-snapshot.tar.gz) preserves the exact source copy, and [dependency.json](dependency.json) records archive/library provenance alongside the GC build logs. No system-wide dependency or security setting was changed.

## Reproduce

Install the project's existing benchmark environment. Download the pinned archive into `build/memory-deps`:

```sh
mkdir -p build/memory-deps
curl -fL https://github.com/bdwgc/bdwgc/releases/download/v8.2.12/gc-8.2.12.tar.gz -o build/memory-deps/gc-8.2.12.tar.gz
shasum -a 256 build/memory-deps/gc-8.2.12.tar.gz
```

Require SHA-256 `42e5194ad06ab6ffb806c83eb99c03462b495d979cda782f3c72c08af833cd4e` before extraction. Extract it, then from its source directory configure with an absolute local prefix:

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools ./configure --prefix=/absolute/path/to/glyph/build/memory-deps/install --disable-shared --enable-static --disable-threads --disable-gcj-support --disable-java-finalization --disable-gc-debug
DEVELOPER_DIR=/Library/Developer/CommandLineTools make -j4
make install
```

For the exact compiler snapshot, extract `source-snapshot.tar.gz` into a fresh directory and run from that directory using the project's virtual-environment Python:

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools /absolute/path/to/glyph/.venv/bin/python -m benchmarks.memory --gc-prefix /absolute/path/to/glyph/build/memory-deps/install --samples 5 --scales 1 4 8 --output-dir /absolute/path/to/new-results
```

Alternatively run the same module from a stable working tree. The harness requires POSIX for RSS measurement and refuses disabled native execution. Generated C and executables remain in that source tree's `build/memory`. Use a fresh output directory to preserve these observations.

## Decision

Proceed with an opt-in GC integration that recognizes pointer-free allocations. Preserve automatic memory handling at the source level and the existing value-record representation. Before making it the default, validate GUI/foreign roots, the self-hosted toolchain, packaging and supported platforms, and collect longer interactive-latency traces. A deterministic scoped arena can be evaluated later for explicitly bounded batches; it needs a checked escape rule or an explicit unsafe contract.
