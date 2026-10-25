# Glyph

Glyph is a compact, statically typed language for agent-written programs. It compiles `.gly` source through C to **Clang/LLVM native executables**. A compiler written in Glyph now compiles its own source; the Python frontend remains the bootstrap/reference implementation and formatter. Generated programs and the bootstrapped native compiler do not require Python to run. This is a small implementation, not a production language or a demonstrated improvement in total agent efficiency.

```gly
total a:[int] = sum(a)

main>void
  print(total([1, 2, 3, 4]))
```

The equivalent loop is supported:

```gly
sum a:[i64]>i64
  s:i64 = 0
  for x:a
    s += x
  ret s
```

## Install and run

Requires Python 3.11+ and a host that permits executing locally compiled programs. The pinned Zig package supplies Clang/LLVM, the native linker and standard C toolchain; a separate LLVM installation is not required.

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[bench]"
.venv\Scripts\glyph check examples\sum.gly --json
.venv\Scripts\glyph run examples\sum.gly
.venv\Scripts\glyph build examples\sum.gly -O2 -o build\sum.exe
.venv\Scripts\glyph fmt examples\sum.gly
```

Linux/macOS shell:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[bench]'
glyph check examples/sum.gly --json
glyph run examples/sum.gly
glyph build examples/sum.gly -O2 -o build/sum
glyph fmt examples/sum.gly --check
```

Installing `.` instead of `.[bench]` omits tokenizer and process-measurement libraries. `python -m glyph` is equivalent to the installed `glyph` command. Activate the virtual environment to put `glyph` on PATH. The source checkout also supports `python -m glyph check` and `fmt` without installing any dependencies. `run` builds first and passes arguments after `--`; e.g. `glyph run benchmarks/programs/recurrence.gly -- 100 2 37`.

Native builds leave generated C next to the executable. `--emit-c path.c` selects a different path. `-O0` through `-O3` are supported; all retain integer/bounds checks. The default is `-O2`, without fast-math or FP contraction. The shared backend cache defaults to `build/.glyph-cache` under the current directory; override with `GLYPH_CACHE_DIR`. The first build may take considerably longer while Zig prepares its C runtime.

If this sandboxed Python distribution cannot bootstrap pip into a venv because of its temp directory, create a workspace `.tmp` directory and set PowerShell `$env:TEMP` and `$env:TMP` to its absolute path before running `python -m ensurepip`. This is an environment workaround, not a Glyph dependency.

## Implemented

* i64, f64, bool, immutable UTF-8 strings; typed variables and functions, recursion, if/else, while, array iteration.
* Homogeneous mutable scalar/record arrays, checked indexing, range/fill/clone/push, numeric left folds, output, explicit numeric conversions.
* Growable `list[T]`, hashed `map[K,V]` and `set[K]`, with shared mutation, cloning and snapshot iteration. See [collections](docs/COLLECTIONS.md).
* Value records with named fields, composition, methods, explicit `mut` receivers, static factories and private members.
* User-defined generic functions/records, tagged unions with exhaustive matching, first-class functions and closures, and interface constraints. See [library abstractions](docs/ABSTRACTIONS.md).
* Checked signed integer arithmetic at all optimization levels, deterministic left-to-right evaluation and short-circuit Boolean operators.
* Inferred local and expression-result types, `int` as an i64 alias, fused `sum`/`count` expressions and equal-length zipped reductions.
* Automatic nonmoving garbage collection for arrays and dynamic strings; shared array references and stable typed pointers. See [memory management](docs/MEMORY.md).
* `glyph check`, `build`, `run`, `fmt`; JSON diagnostics with stable codes and source spans; canonical formatting.
* Optional native GUI library on macOS: windows, labels, buttons and a blocking event loop, with a calculator written in Glyph.
* UTF-8 text operations, file access, string arguments and POSIX process execution.
* Binary file reads/writes, blocking chunked I/O with checked handles, and JSON validation, lookup, quoting and construction. See [binary I/O and JSON](docs/SYSTEMS.md#binary-and-streaming-io).
* Blocking TCP client/server sockets, HTTP with verified TLS through optional system libcurl, SQLite prepared statements through optional system SQLite, and CSV/Base64 serialization. See [services and dependencies](docs/SERVICES.md).
* Recoverable `try_` parsing, file and process operations returning typed result records with error codes and messages. See [error handling](docs/SYSTEMS.md#recoverable-failures).
* Named file imports with isolated module names, shared dependency identity and circular-import diagnostics.
* A self-hosted compiler with a verified three-stage bootstrap and native regression checks.

Start with [the little Glyph manual](docs/MANUAL.md), or read [the specification](docs/SPEC.md), [architecture and tradeoffs](docs/ARCHITECTURE.md), and [the short agent guide](docs/AGENT_GUIDE.md). Examples are in [examples](examples/).

Garbage collection can pause execution and conservatively retain unused storage; live slices keep their entire backing allocation alive. `push` copies and is O(n). Inheritance, runtime interface dispatch, concurrency, scoped regions and alternate presentation layers are not implemented. These are future work. The frontend is deliberately small and has not been hardened against hostile resource-exhaustion inputs.

## Self-hosting

```sh
python selfhost/bootstrap.py --verify
build/selfhost/glyphc run examples/records.gly -o build/records
build/selfhost/glyphc build selfhost/compiler.gly -o build/glyphc-next
```

The bootstrap uses Python once, then builds two generations with the native
compiler and requires identical generated C. Native generations run without
Python on `PATH`. On the development Mac, prefix the bootstrap command with
`DEVELOPER_DIR=/Library/Developer/CommandLineTools` to select the verified SDK.
See [self-hosting instructions and boundaries](docs/SELF_HOSTING.md) and the
[systems-library API](docs/SYSTEMS.md). The installed `glyph` command continues
to use the reference Python frontend; `build/selfhost/glyphc` is the native
compiler. Native build orchestration currently requires a POSIX host.

## Graphical applications

On macOS with Xcode or Apple's Command Line Tools installed:

```sh
python -m glyph run examples/calculator.gly
python -m glyph run examples/gui_hello.gly
```

The [GUI library guide](docs/GUI.md) documents the `gui_*` API, event loop and
current limits. GUI executables link a bundled AppKit backend; console programs
keep their existing portable build path. The initial GUI backend is macOS-only.

Records use value semantics and static method dispatch:

```gly
type Point
  x:f64
  y:f64
  norm2 = self.x * self.x + self.y * self.y
  mut move dx:f64, dy:f64>void
    self.x += dx
    self.y += dy

main>void
  p := Point(3.0, 4.0)
  q := p
  q.move(1.0, 0.0)
  print(p.norm2())
  print(q.norm2())
```

This prints 25 then 32. Records compile to C structs; methods become ordinary native functions. Array fields continue to share storage when a record is copied. See [record examples](examples/records.gly) and [the detailed value and mutation rules](docs/SPEC.md#value-records-and-methods).

## Verification and measurements

```sh
python -m unittest discover -s tests -v
python -m benchmarks.agent
python -m benchmarks.runtime --samples 5
python -m benchmarks.reductions --samples 15
python -m benchmarks.report
```

Tests cover rejection diagnostics and spans, formatting idempotence, native examples, evaluation order and aliasing, runtime traps, CLI behavior, and 150 seeded differential arithmetic cases. The GitHub Actions workflow runs tests and measurements on Linux and Windows and uploads raw JSON artifacts. The workflow must run on an approved runner before its results can be claimed.

See [verification status](docs/VERIFICATION.md) and [benchmark methodology and results](benchmarks/README.md). The agent benchmark contains three authored task solutions and a scripted one-error repair exercise. It is **not** a sampled-agent study. `benchmarks.score_transcripts` can score real externally recorded trials, including costs of failed tasks. Missing real agent costs are reported as null, not zero.

Native verification completed on macOS arm64 on 2026-10-19: all 10 tests passed without skips and all benchmark outputs verified across five measured trials. See the separate [macOS report](benchmarks/results/macos-arm64-2026-10-19/REPORT.md) and [SDK setup and run provenance](docs/VERIFICATION.md#native-verification-on-macos).

The 2026-10-20 inference/reduction update passes 19 tests. Its three Glyph function fixtures use 49 AI BPE tokens versus Python's 47, down from 110; guarded integer sum is about 2.6× faster than the checked loop on the measured small-integer workload. See [current verification and limits](docs/VERIFICATION.md), [measured report](benchmarks/results/macos-arm64-2026-10-20/REPORT.md), and [reduction examples](examples/reductions.gly). These results do not establish total AI generation-cost parity or general C-speed execution.

The subsequent record/method update passes all 28 tests without skips on macOS arm64, including copy and receiver-order fixtures at `-O0`, `-O2` and `-O3`. Its [native verification logs and provenance](benchmarks/results/macos-arm64-2026-10-20-records/verification.json) are separate from the earlier timing and source-token measurements.

On the initial development machine, native binaries compile successfully but Microsoft Defender Exploit Guard blocks execution (IT rule `01443614-CD74-433A-B99E-2ECDC07BFC25`), including a minimal C executable. Runtime verification and native timing therefore require an approved runner. No security settings are changed by this project. `GLYPH_SKIP_EXECUTION=1` allows tests to compile fixtures and explicitly **skip** execution; benchmark `--skip-native-execution` records only compilation, token inventory and Python observations. Those modes are partial verification, never passing native runtime evidence.

## Multi-file programs

Use `import square, Counter from "./math.gly"` to select functions and record
types from another file. Paths are relative to the importing file, and helpers
remain scoped to their module. Both compilers support imports; the self-hosted
compiler now uses them itself. See [module rules](docs/MODULES.md) and
[the runnable example](examples/modules/main.gly).
