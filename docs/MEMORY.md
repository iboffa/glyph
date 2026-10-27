# Memory management

Glyph uses **automatic, nonmoving tracing garbage collection** for arrays and
dynamically created strings. The bundled collector is Boehm–Demers–Weiser GC
(BDWGC) 8.2.12. There are no new language keywords, ownership annotations, manual
free calls or reference-count operations for the programmer to write.

Records remain inline C struct values. Assignments and calls copy record values;
array fields still share their backing storage. Arrays of numbers, booleans and
recursively pointer-free records use allocations that the collector does not
scan. String bytes use the same allocation class. Arrays containing strings,
arrays or raw pointers are scanned for references. Allocation preserves zero
initialization, including for pointer-free storage.

Unreachable allocations, including cycles, can be reclaimed during execution.
Live array aliases, string slices and supported interior pointers preserve their
backing storage. Storage does not move. `clone` still makes a shallow element
copy; `push` still allocates and copies the old elements. Collection does not
change either operation's cost or sharing semantics.

## Boundaries

- Collection is conservative and timing is unspecified. Values that resemble
  pointers can retain otherwise unreachable objects. Heap capacity and process
  RSS need not fall immediately after objects become unreachable.
- A live slice retains its whole backing allocation. Repeated concatenation or
  `push` can still do quadratic copying even when intermediates are reclaimed.
- Collection can pause execution; this is not a hard real-time guarantee.
- Sequential programs use the single-threaded collector. Concurrent programs
  use threaded BDWGC and collector-aware pthread creation/join. AppKit owns
  copies of text supplied to it; its threads do not access Glyph heap objects.
  See [concurrency](CONCURRENCY.md) for the checked sharing and root policy.
- GC manages memory, not external resources. File operations close their handles
  explicitly, and the GUI backend still handles window/native-object cleanup.
- Unsafe out-of-bounds pointers remain unsafe. Keeping an integer that happens
  to encode an address is not a supported way to preserve an allocation.

## Building and verification

The release source, original notices and per-file hashes live under
`glyph/vendor/bdwgc`. Builds need no GC download or system installation.
Python builds cache a collector object using source, toolchain, host and SDK
identity. The self-hosted compiler compiles the upstream amalgamation alongside
the generated C, so its build driver needs no Python. On macOS, upstream
`LARGE_CONFIG` accommodates the root ranges loaded by AppKit.

Generated C is inspectable, but compiling it manually now requires the bundled
`include` directory, `GC_NOT_DLL` and the collector object. Use either Glyph
build driver to supply the correct flags automatically. The collector is built
with interior-pointer support, compiler atomic primitives and non-executable
heap pages. Incremental collection is disabled; allocation can trigger a full
collection. This also avoids installing unused incremental fault handlers.
No fallback silently reverts to retaining all allocations.

`GLYPH_GC_STRESS=1` forces a full collection before every Glyph allocation for
diagnostics. It is intentionally slow. Regression tests cover live slices,
heap-held interior and one-past pointers, cycles, aliases, shallow clones,
nested records, empty arrays, automatic reclamation and AppKit events. The
historical [strategy comparison](../benchmarks/results/macos-arm64-2026-10-21-memory/REPORT.md)
motivated this choice; it is workload evidence, not universal C-speed parity.

## Growable collections

Lists, maps and sets use shared, scanned GC-owned headers. Growth replaces an
internal buffer while preserving the header identity. Buffers use atomic
allocation only for pointer-free element types. Delete/clear zero removed
references; clear retains capacity. Collection cycles are collectible. No raw
collection-buffer pointers are exposed. Clones and iteration snapshots are
shallow copies. See [Collections](COLLECTIONS.md).


## Concurrent roots and publication

Parallel-map inputs are numeric, outputs are fresh and disjoint, and callback
captures cannot contain mutable references. Task closure environments, result
storage and descriptors are scanned allocations. A lexical scope roots its
children until joining; returned safe values retain ordinary GC lifetime.
Channels hold scanned bounded buffers, clear consumed slots, and use registered
worker stacks to root blocked sender payloads. Mutexes publish buffer updates;
pthread creation and joining publish task inputs/results. GC finalizers destroy
unreachable channel synchronization objects; close does not destroy them while
another alias or blocked operation can still use them.

GC stress configuration is initialized before threads start. Error source paths
are thread-local. Collection remains enabled and stop-the-world; allocation-free
workers can pause when another thread collects. Thread safety is not ownership:
shallow clones and record/closure snapshots still share referenced storage, so
those graphs are rejected at concurrency boundaries. The CPU pool shuts down
and joins at normal main completion; scoped threads join at each scope exit.
