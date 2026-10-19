# Glyph

Glyph is a compact, statically typed language for agent-written programs. A Python frontend compiles `.gly` source through C to **Clang/LLVM native executables**. Generated programs do not require Python. This is a small implementation, not a production language or a demonstrated improvement in total agent efficiency.

```gly
sum a:[i64]>i64 = fold a 0 +

main>void
  print(sum([1, 2, 3, 4]))
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
* Homogeneous mutable scalar arrays, checked indexing, range/fill/clone/push, numeric left folds, output, explicit numeric conversions.
* Checked signed integer arithmetic at all optimization levels, deterministic left-to-right evaluation and short-circuit Boolean operators.
* Explicit program-arena ownership with shared array references; unsafe typed pointers into stable array storage.
* `glyph check`, `build`, `run`, `fmt`; JSON diagnostics with stable codes and source spans; canonical formatting.

Read [the specification](docs/SPEC.md), [architecture and tradeoffs](docs/ARCHITECTURE.md), and [the short agent guide](docs/AGENT_GUIDE.md). Examples are in [examples](examples/).

Arrays are retained until process exit; repeated allocation can consume substantial memory. `push` copies and is O(n). There are no imports, structs, closures, user generics, file I/O, concurrency, scoped regions or alternate presentation layer. These are future work. The frontend is deliberately small and has not been hardened against hostile resource-exhaustion inputs.

## Verification and measurements

```sh
python -m unittest discover -s tests -v
python -m benchmarks.agent
python -m benchmarks.runtime --samples 5
python -m benchmarks.report
```

Tests cover rejection diagnostics and spans, formatting idempotence, native examples, evaluation order and aliasing, runtime traps, CLI behavior, and 150 seeded differential arithmetic cases. The GitHub Actions workflow runs tests and measurements on Linux and Windows and uploads raw JSON artifacts. The workflow must run on an approved runner before its results can be claimed.

See [verification status](docs/VERIFICATION.md) and [benchmark methodology and results](benchmarks/README.md). The agent benchmark contains three authored task solutions and a scripted one-error repair exercise. It is **not** a sampled-agent study. `benchmarks.score_transcripts` can score real externally recorded trials, including costs of failed tasks. Missing real agent costs are reported as null, not zero.

On the initial development machine, native binaries compile successfully but Microsoft Defender Exploit Guard blocks execution (IT rule `01443614-CD74-433A-B99E-2ECDC07BFC25`), including a minimal C executable. Runtime verification and native timing therefore require an approved runner. No security settings are changed by this project. `GLYPH_SKIP_EXECUTION=1` allows tests to compile fixtures and explicitly **skip** execution; benchmark `--skip-native-execution` records only compilation, token inventory and Python observations. Those modes are partial verification, never passing native runtime evidence.
