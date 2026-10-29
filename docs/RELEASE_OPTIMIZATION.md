# Reproducible release builds

Both drivers accept `--lto none|thin|full`, `--cpu portable|native`,
`--profile-generate PATH`, `--profile-use FILE`, `--cc PATH`, `--alloc-stats`,
`--gc-timing`, `--zero-init`, `--no-optimize` and `--opt-report PATH` alongside
`-O0`–`-O3`. Portable targeting and no LTO/PGO remain defaults. Arithmetic remains
checked; every build retains `-fno-fast-math -ffp-contract=off`.

The tested release toolchain is Apple Clang and its matching `llvm-profdata`.
The default Zig backend remains available. LTO/PGO support depends on the selected
compiler/linker; unsupported flags are backend errors, never silently ignored.
Native CPU targeting produces machine-specific executables. The native driver's
current spelling selects `-mcpu=native` on macOS and `-march=native` on other POSIX
systems; macOS x86 and Linux ARM require further target detection before this
option is portable across those hosts. Portable builds avoid this limitation.

A reproducible workflow, including distinct training and held-out inputs:

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python \
  -m benchmarks.release_workflow --frontend reference --samples 7
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python \
  -m benchmarks.release_workflow --frontend native --samples 7
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python \
  -m benchmarks.release_workflow --frontend native --compiler-workload --samples 7
```

The script emits C once, instruments that unchanged path, trains in a fresh
profile directory, merges with the matching toolchain and builds portable,
thin/full LTO, native CPU, PGO and PGO+thin-LTO variants. Stale profile/function
mismatches are errors. It retains exact commands, input/profile/source hashes,
training output, two compilation samples, executable sizes and seven randomized
held-out measurements after warmup. Compiler trials compare generated C hashes,
not just successful exit status. Array training sizes/seeds differ from evaluation;
compiler training checks small example programs, while evaluation emits the
frozen baseline compiler itself.

The workflow uses the shared reference C build helper for both frontends' emitted
C, isolating frontend output from driver differences. Its bundled collector object
is built separately at O2 without application PGO/LTO. The native standalone driver
can also apply these flags when compiling its bundled collector source; that is
a different build configuration and should not be conflated with this comparison.
PGO is a workload-specific experiment, not a universally faster release preset.

## Measurements and interpretation

`--alloc-stats` records allocation requests/bytes by managed, arena and owned
domains, final collector capacity/free bytes and collection count. Arena counts
refer to logical buffer requests, not chunk malloc calls. Stack allocations are
not heap requests. Occupied collector capacity is not an exact live-byte measure.

`--gc-timing` uses BDWGC event callbacks and POSIX clocks. It records collection
wall times, collector-thread CPU time and the interval after the world stops and
before it starts. It excludes thread suspension/resumption time from that last
metric. Samples are capped at 4096; total counts expose truncation. It does not
label batch latency as a GC pause. Collector-thread CPU excludes time spent by
other threads. Windows event timing is not supported by the reference driver.
The native driver currently relies on its POSIX host requirement.

Instrumentation uses relaxed atomic allocation counters and collector callbacks.
It is disabled in primary timing runs. Instrumented measurements and uninstrumented
peak-RSS controls are stored separately to expose its overhead. No default runtime
logging, process-global GC switch, fast-math flag or moving allocator is introduced.
