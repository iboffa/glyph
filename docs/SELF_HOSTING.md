# Self-hosting Glyph

Glyph now has a compiler written in Glyph: [`selfhost/compiler.gly`](../selfhost/compiler.gly).
It implements lexing, parsing, type checking, type inference and C generation,
including records/methods, user generics, tagged unions, closures, interface constraints, lists/maps/sets, reductions, structured concurrency, unsafe array pointers, the systems library,
file imports, and the optional GUI API. It can compile that same source into another native
compiler. Clang/LLVM still supplies the machine-code backend and linker.

The Python implementation remains the bootstrap/reference frontend and formatter.
The existing `glyph` / `python -m glyph` command still invokes it. Use the
bootstrapped `glyphc` executable for compilation without Python.

## Bootstrap and verify

From the repository root, with the existing Python dependencies and a C compiler
installed:

```sh
python selfhost/bootstrap.py --verify
```

On the development Mac, select the previously verified Command Line Tools SDK for
Zig's stage-0 build:

```sh
GLYPH_TEST_GUI=1 DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python selfhost/bootstrap.py --verify
```

`GLYPH_TEST_GUI=1` enables brief real-window tests. Omit it on a host without a
desktop session. `--cc /absolute/path/to/clang` selects the native stages' C
compiler. `--output-dir path` selects a build directory; it defaults to
`build/selfhost`.

The bootstrap performs these steps:

1. The Python compiler builds `compiler.gly` into `stage1`.
2. `stage1` compiles the same Glyph source into `stage2`.
3. `stage2` compiles the same source into `glyphc` (stage 3).
4. The generated C from stages 2 and 3 must be byte-for-byte identical.
5. Stage 3 checks its own source and builds/runs an argument-handling smoke test.
6. With `--verify`, the existing language tests run through native checking and
   native C generation, alongside dedicated native-driver tests.

Steps 2–5 run with an empty executable-search `PATH` and an explicitly selected
C compiler. Python is unavailable through that path. No native compiler stage
launches Python, reads Python compiler source, or recognizes its own source as a
special case. The `.gly` files contain the actual compiler algorithms. `compiler.gly` imports
its text utilities from `text.gly`, so rebuilding also exercises module resolution.

The script writes commands, timings, hashes and the fixed-point result to
`build/selfhost/verification.json`, plus detailed output in `bootstrap.log`.
The corpus report records how many native checks and C emissions were exercised.
The fixed point establishes reproducibility across these stages; the separate
language tests provide behavioral evidence. Neither is a proof of compiler
correctness for every possible program.

## Use the native compiler

```sh
build/selfhost/glyphc check examples/records.gly
build/selfhost/glyphc run examples/records.gly -o build/records
build/selfhost/glyphc emit-c examples/sum.gly -o build/sum.c
build/selfhost/glyphc build examples/calculator.gly -o build/calculator

# Rebuild the compiler using the compiler itself:
build/selfhost/glyphc build selfhost/compiler.gly -o build/glyphc-next
```

The native driver supports `check`, `emit-c`, `build`, and `run`, plus `-o`,
`-O0` through `-O3`, `--runtime-dir`, `--cc`, `--json`, and program arguments after
`--`. It passes argument arrays directly to child processes, without a shell.
For example:

```sh
build/selfhost/glyphc run benchmarks/programs/recurrence.gly -o build/recurrence -- 100 2 37
```

The default runtime source directory is `glyph` relative to the working directory.
From another directory, pass `--runtime-dir /path/to/glyph/glyph`, or set
`GLYPH_RUNTIME_DIR`. Emitting/building programs needs the runtime headers, and GUI
builds additionally need `gui_macos.m`. Native compilation uses `CC` or `cc` unless
`--cc` is supplied; `--cc` names one executable, not a shell command with flags.
GUI builds use `xcrun clang` and AppKit. The resulting application executables do
not need Python or these source headers to run.

Native builds leave generated C at `<output>.c`. Without `-o`, the default output
is `<source>.out` (`<source>.c` for `emit-c`). Output directories must already exist.
Source/output aliases, including existing symlinks and hard links, are rejected.

## Current boundaries

- Native process execution/build orchestration currently requires a POSIX host.
  The bootstrap has been verified on macOS arm64; Linux execution is not yet
  verified. The GUI backend still requires macOS.
- Formatting remains available through the Python `glyph fmt` command. There is
  no native formatter yet. Named file imports work in both compilers; see [Modules](MODULES.md).
- The compiler uses source-sized storage and limits combined source input to 1 MiB across at most 128 files. It
  uses the default nonmoving collector, including temporary text and AST storage.
  The native driver builds the bundled collector from `--runtime-dir` without
  Python or a system GC installation. It is not an incremental compiler. It is not hardened against hostile resource-exhaustion input.
- Frontend diagnostics are JSON with source locations and the established `G`
  codes. Error wording and the first error chosen for malformed input can differ
  from the reference frontend. Driver usage/path errors are currently text;
  systems-library I/O failures use runtime diagnostics and status 70.
- Self-hosting does not mean that LLVM, the linker, the C runtime or AppKit are
  written in Glyph. The dependency on the Python compiler ends after stage 1.

See [the systems-library API](SYSTEMS.md) for the small language additions used
by the compiler and [verification status](VERIFICATION.md) for recorded results.


Concurrent programs emitted by the native compiler include the same
`concurrency_runtime.h` used by the reference backend. The native driver enables
GC_THREADS and pthreads only for marked programs; its runtime distribution must
include this header and the bundled collector thread sources. The
[concurrency verification report](../benchmarks/results/macos-arm64-2026-10-27-concurrency/REPORT.md)
records native acceptance/diagnostics, C emission, three-stage fixed-point and
packaged-runtime execution evidence without Python on PATH.

## Allocation controls and release builds

The native frontend also checks `@noalloc`, scoped primitive arenas, affine local
owners and borrows, and applies bounded allocation optimizations. The native
driver accepts the [release flags](RELEASE_OPTIMIZATION.md), including PGO/LTO,
portable/native targeting, `--no-optimize`, `--opt-report`, `--alloc-stats`,
`--gc-timing` and `--zero-init`. The [memory report](../benchmarks/results/macos-arm64-2026-10-28-memory/REPORT.md) retains fixed-point and differential evidence, including limits on native optimization reports.
