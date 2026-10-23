# Default garbage collector integration — 2026-10-21

Glyph now uses bundled BDWGC 8.2.12 for arrays and dynamic strings in both the
Python and self-hosted compilers. Records remain inline values. Pointer-free
arrays and string buffers use atomic allocations; reference-bearing arrays use
scanned allocations. Array sharing, shallow cloning, stable pointers and source
syntax are unchanged.

## Verification

- The reference-emitter suite and native checking/emission suite each passed
  all 57 test methods without skips, including real AppKit controls/events.
- Native checking/emission performed 1,590 source checks, 49 C emissions and
  1,479 parser-rejection observations. The Python checker is the differential
  reference; the native compiler supplies C for runtime fixtures.
- A three-generation bootstrap reached byte-identical stage-2/stage-3 C.
  Native generations and the argument-bearing smoke test used an empty `PATH`
  and an absolute C compiler path, without Python available on `PATH`.
- Full collection before every allocation preserved heap-held string slices,
  interior and one-past pointers, cyclic graphs, shared aliases and clones at
  O0, O2 and O3. Nested record and empty-array cases also passed.
- The extracted wheel contained all 68 upstream files with matching hashes.
  It built and ran a console program, built the GUI example, and supplied the
  runtime for a native-driver build/run without a system GC installation.
- Final collector configuration and a generated console program cross-compiled
  and linked for x86_64 Linux GNU and Windows GNU with Zig 0.14.1. These binaries
  were **not executed** on those systems. CI now includes macOS alongside the
  existing Linux and Windows jobs; those remote jobs were not run here.
- Optimized LLVM inspection still found matching sum/fold opcode counts.
  Formatting of the native compiler and `git diff --check` passed.

## Automatic reclamation

These are actual generated functions called for 4,096 batches. No explicit
collection is requested in these workloads. Output checksums match independent
expected values. Heap capacity below is reported by BDWGC at the end; it is
**not process peak RSS**, live bytes, or a latency measurement.

| Workload | Cumulative GC allocation | Final GC heap capacity |
|---|---:|---:|
| Numeric arrays | 256.125 MiB | 0.5 MiB |
| Temporary strings | 146.250 MiB | 0.25 MiB |
| Cyclic graphs | 24 MiB | 0.25 MiB |

The regression test requires each workload to allocate over 16 MiB while
keeping heap capacity below 8 MiB. These checks demonstrate reclamation for
the fixtures, not bounded memory for every application. See `heap-checks.json`.
The earlier [strategy experiment](../macos-arm64-2026-10-21-memory/REPORT.md)
contains performance comparisons; this integration does not establish a new
general speed claim.

## Integration findings

AppKit exceeded BDWGC's default 2,048 static root ranges. macOS builds now use
upstream `LARGE_CONFIG` (8,192 ranges). Incremental collection is explicitly
disabled; it was not enabled by the runtime, and its unused macOS fault handlers
caused linker warnings to precede JSON runtime diagnostics. The final bootstrap
and packaged native build no longer emit those warnings. Both changes use
upstream configuration flags; vendored source files are unmodified.

The native compiler now sequences `push` length checking before allocation,
matching the Python emitter and avoiding duplicate unsequenced diagnostic-path
assignments within one C call.

The collector is single-threaded, nonmoving and conservative, with interior
pointers enabled. It can pause execution and retain unreachable objects due to
conservative roots. Live slices retain entire backing allocations. External
resources still require their existing explicit cleanup. See
[memory semantics and build details](../../../docs/MEMORY.md).

## Evidence and reproduction

`verification.json` records host/toolchain information, source hashes, wheel
hash and commands. `bootstrap.json`, `bootstrap.log` and `native-corpus.json`
record the bootstrap and native suite. `reference-tests.log`,
`package-check.log`, `wheel.log`, `cross-compile.json`, `cross-compile.log` and
`codegen.json` contain the other checks. `source-snapshot.tar.gz` preserves the
tested implementation, tests and vendored collector.

On this macOS host, native commands used
`DEVELOPER_DIR=/Library/Developer/CommandLineTools` to select the working SDK.

```sh
GLYPH_TEST_GUI=1 python selfhost/bootstrap.py --output-dir build/selfhost-gc --verify
GLYPH_TEST_GUI=1 GLYPH_SELFHOST="$PWD/build/selfhost-gc/glyphc" python -m unittest discover -s tests -v
python -m glyph fmt --check selfhost/compiler.gly
git diff --check
```

The GUI flag requires a macOS desktop session. Ordinary test runs skip the real
window test. Historical allocator comparisons must be run from their own saved
source snapshot because they rewrite the former arena runtime.
