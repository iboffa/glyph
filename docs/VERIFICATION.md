# Verification status

## Service hardening and platform execution — 2026-10-25

[The complete CI matrix passed](https://github.com/iboffa/glyph/actions/runs/40192542698)
on revision `6b48265541718af441c30079fd9118051b0487b2`, including the benchmark
commands. Each reference suite contains 106 tests. Optional curl/SQLite tests
are enabled on all three platforms; they are not skipped on Windows.

| Host | Reference tests passed / skipped | Native corpus passed / skipped |
| --- | --- | --- |
| Ubuntu x86-64 | 101 / 5 | 104 / 2 |
| Windows x86-64, MSYS2 UCRT64 | 96 / 10 | Native build driver remains POSIX-only |
| macOS 15 arm64, Xcode 16.4 | 100 / 6 | 103 / 3 |

Skips are explicit platform/opt-in cases: live GUI, macOS-only GUI builds,
Linux `/dev/full`, POSIX `/dev/stdin` and EINTR injection, and native-driver
checks in the reference suite. Both POSIX native bootstraps reached a stage
2/3 fixed point without Python on their tool PATH. CI uploads reference logs,
bootstrap provenance and native corpus reports as `glyph-results-*` artifacts.

Eight additional failure-path tests cover interrupted waits/transfers, short
socket transfers, peer resets, descriptor cleanup under a low limit,
truncated HTTP bodies, oversized headers/body limits, SQLite lock contention,
rollback on close, failed prepares/finalizes, and file read/write/close errors.
TCP now keeps one monotonic deadline across interrupted waits and partial
transfers, using nonblocking sockets internally behind its blocking API.

Windows execution also exposed and fixed two portability problems: automatic
CRLF checkout conversion broke vendored-file hashes, and narrow CRT arguments
lost Unicode. Checkout attributes now preserve vendor bytes. Both emitters
initialize UTF-8 arguments from the wide Windows command line; text/binary file
access and file identity/existence use wide APIs. A regression round-trips
Unicode and quoted arguments, Unicode filenames and hard-link identities.

CI selects macOS 15/Xcode 16.4 because the pinned Zig 0.14.1 failed to link
standard C symbols with the macOS 26 SDK selected by `macos-latest`. This is a
toolchain compatibility limit, not evidence of macOS 26 SDK support. GCC's
isolated bootstrap PATH now contains assembler/linker tools, while still
excluding Python and a shell. Windows native compiler orchestration and
Windows process spawning remain outside this implementation.

The final local Mac runs also passed: reference 106 tests (six skips), native
106 tests (three skips), 1,708 native checks and 99 native emissions. The final
bootstrap's compiler/runtime hashes match the working sources. Local logs are
`build/hardening-reference-final.log` and `build/hardening-native-final.log`;
provenance and the corpus report are in `build/hardening-selfhost-final/`.
Downloaded CI evidence is in `build/ci-results/`. All are ignored build outputs.

## Network, database and serialization services — 2026-10-24

Both compilers now expose blocking TCP client/server sockets, libcurl-backed
HTTP with peer/hostname TLS verification, SQLite connections and prepared
statements, CSV, and strict Base64. HTTP/SQLite are optional system link
dependencies; ordinary programs do not include their adapters.

Verified on the development Mac with the Command Line Tools SDK:

* Full reference suite: 97 tests, 91 passed, six expected skips (optional live
  GUI, three native-driver tests, two Linux `/dev/full` cases).
* Full native corpus: 97 tests, 94 passed, three expected skips (optional live
  GUI and two `/dev/full` cases), with 1,698 native checks and 92 emissions.
* Focused tests exercise loopback TCP and timeouts, binary HTTP, non-2xx status
  and redirects, response limits, trusted HTTPS and rejection of both an
  untrusted certificate and a hostname mismatch. Tests generate temporary
  certificates and do not modify system trust. SQLite tests cover copied
  parameter bindings, embedded NUL, blobs, SQL NULL, explicit transactions,
  error/reset behavior, UTF-8 rejection and resource lifetimes under forced GC.
  CSV and Base64 results are compared with Python's standard libraries.
* After correcting optional dependency detection for user function prefixes,
  the final three-stage bootstrap reached a fixed point without Python on PATH
  in native generations. A direct regression confirmed `try_db_user` does not
  pull in SQLite in either emitter. Both build drivers also linked and ran a
  program combining TCP, HTTP and SQLite.
* Database and serialization examples ran through both compilers; the native
  driver also built the HTTP example. Example formatting and diff checks passed.
* The TCP fixture compiled to Linux x86-64 and Windows x86-64 object files.
  This verifies compilation only, not linking or execution on those platforms.

The sandbox initially denied loopback socket binding; network execution was
then verified outside that sandbox. The service tests make no external HTTP
requests. The build's optional library versions are host dependencies, not
vendored or pinned versions.

Local logs are `build/services-reference.log`, `build/services-native.log`,
`build/services-focused.log`, and `build/services-final-bootstrap.log`.
`build/services-selfhost/corpus/report.json` holds the full native-corpus
result; `build/services-final-selfhost/verification.json` holds the final
bootstrap source/runtime hashes. Build artifacts are ignored by Git.

Reproduce in an environment permitting loopback servers:

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m unittest discover -s tests -v
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python selfhost/bootstrap.py --verify --output-dir build/services-final-selfhost
```

See [Services](SERVICES.md) for dependency setup, blocking/timeout semantics,
handle cleanup, and the limits of this initial API. Linux/Windows service
execution and network performance remain unverified by this run.

## Binary/streaming I/O and JSON — 2026-10-24

The first library slice supplies byte-array file access, blocking chunked I/O
with explicit close and checked handles, UTF-8 conversion, and JSON validation,
lookup and construction. Both compilers expose the same API. JSON failures use
`R012`, separately from the existing `R011` missing-map-key diagnostic.

Verified on the development Mac using
`DEVELOPER_DIR=/Library/Developer/CommandLineTools`:

* Reference suite: 89 tests, 83 passed, six explicit skips (optional live GUI,
  three native-driver tests, and two Linux `/dev/full` cases).
* Three-stage bootstrap: identical stage 2/3 generated C; native generations
  ran without Python on PATH. Native corpus: 89 tests, 86 passed, three skips
  (optional live GUI and two `/dev/full` cases), with 1,684 native checks and
  82 native emissions.
* Isolated focused native-emitter run: nine binary/JSON tests, eight passed,
  `/dev/full` skipped. Coverage includes all byte values, chunk boundaries,
  nonseekable pipe input, stale handles, Unicode escapes, malformed JSON,
  the 128-container nesting bound, exact numeric lexemes, 100 seeded JSON
  round-trips, and forced collection preserving JSON storage and open handles.
* `examples/binary_json.gly` ran through both compilers and round-tripped its
  output against Python's JSON decoder. Formatting and diff whitespace checks
  passed.

Local generated logs/reports are in `build/io-json-final-tests.log`,
`build/io-json-final-bootstrap.log`,
`build/io-json-final-selfhost/verification.json`, and
`build/io-json-native-focused.log`; these build artifacts are ignored by Git.
Reproduce with:

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m unittest discover -s tests -v
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python selfhost/bootstrap.py --verify --output-dir build/io-json-final-selfhost
```

Linux and Windows execution of these new APIs was not verified in this run.
Bytes currently occupy `[int]` storage; JSON operations reparse text rather
than retaining a dynamic tree. These are documented first-slice limitations,
not performance claims.

## Library abstractions — 2026-10-22

Both compilers implement explicit generic functions and records, generic tagged
unions with exhaustive matching, first-class function values and snapshot
closures, and interfaces used as static generic constraints.

The full reference run completed 80 tests: 75 passed and five were explicitly
skipped (optional live GUI, three native-driver tests, and Linux `/dev/full`).
The full native run completed 80 tests: 78 passed, with only live GUI and
`/dev/full` skipped. It exercised 1,667 native checks, 73 native C emissions,
and 1,479 parser rejections. The native-driver tests passed in this run.
Stages 2 and 3 of the bootstrap emitted identical C; native generations ran
with no Python on PATH.

After those full runs, a module value/type namespace edge case was fixed.
All 21 module and abstraction tests then passed through reference checking and
native emission, with no skips. Coverage includes explicit specialization,
recursive/nested records, private factories, imported constraints, exhaustive
return analysis, recursive unions, function fields and containers, nested and
escaping closures, snapshot versus shared-reference captures, forced GC,
callee/argument order, invalid contracts, and bounded runaway specialization.

[Saved verification and source hashes](../selfhost/results/abstractions-macos-arm64-2026-10-22/verification.json)
include the full bootstrap report; adjacent logs preserve the reference and
final focused runs. The verified compiler is `build/abstractions-selfhost/glyphc`.
Builds used `DEVELOPER_DIR=/Library/Developer/CommandLineTools`. Linux/Windows
native execution and new performance claims are outside this verification.
See [syntax and limits](ABSTRACTIONS.md) and the runnable
[combined example](../examples/abstractions.gly).

## Recoverable results — 2026-10-21

The reference suite ran 72 tests on macOS arm64: 67 passed, with the optional
live-GUI test, three native-driver tests and Linux `/dev/full` check skipped.
The native compiler passed the existing 66-test corpus (65 passed, live GUI
skipped) and a separate six-test result corpus (five passed, `/dev/full`
skipped). The native-driver tests passed in the native run. The native verifier
now includes `test_results` in its normal corpus.

Result coverage includes invalid numbers, overflow, embedded NUL, invalid
UTF-8, missing files, failed output opens, successful/empty file round trips,
process launch errors and nonzero child exit status, custom error construction,
explicit propagation through imported functions, arrays/collections, and type
rejections. Existing fatal runtime diagnostics still pass. The three-stage
bootstrap reached identical generated C in stages 2 and 3. The runnable result
example reports two errors, prints `42`, and finishes with status zero.

Local evidence is in `build/results-python-tests.log`,
`build/selfhost-results/verification.json`, `build/selfhost-results/bootstrap.log`,
and `build/selfhost-results/result-corpus/report.json`. Builds used
`DEVELOPER_DIR=/Library/Developer/CommandLineTools`; running the example with
the default Xcode SDK reproduced the previously documented standard-C linker
failure, resolved by selecting the Command Line Tools SDK. Linux/Windows native
execution and the `/dev/full` write/close failure test were not verified here.

## Collections — 2026-10-21

Lists, maps and sets passed the complete 66-test regression suite on macOS arm64
through both frontends. The reference run passed 62 tests with four explicit
skips (the optional live-GUI test and three native-driver tests). The native run
passed 65 tests with only the optional live-GUI test skipped; it exercised 1,622
native checks and 62 native C emissions, including the driver tests.

Nine new collection tests cover typed empty constructors, diagnostics, imported
record types, aliasing/cloning, snapshots, argument order, map/set growth and
deletion against a seeded Python reference, runtime traps, and recursive graphs
under forced GC at O0/O2/O3. The three-stage bootstrap reached identical generated
C in stages 2 and 3. A wheel was built, inspected for the collection module/header,
and its extracted compiler built and ran the collection example.

Commands (with `DEVELOPER_DIR=/Library/Developer/CommandLineTools` on this Mac):

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python selfhost/bootstrap.py --output-dir build/collections-selfhost
.venv/bin/python selfhost/verify.py build/collections-selfhost/glyphc --output-dir build/collections-selfhost/corpus
```

Local logs are in `build/collections-reference-regression.log`,
`build/collections-native-regression.log` and `build/collections-selfhost/`.
Formatting and diff whitespace checks passed. This update does not establish
collection performance measurements or execution on other operating systems.
See [collection semantics and costs](COLLECTIONS.md).

## Default garbage collection — 2026-10-21

The reference and self-hosted compiler suites each passed all 57 tests without
skips on macOS arm64, including real AppKit events and forced-collection tests
at O0/O2/O3. The native compiler reached a three-stage fixed point with no Python
on the native stages' `PATH`. Packaged builds and Linux/Windows cross-compilation
passed; execution on those other hosts remains unverified. Automatic reclamation
kept final collector heap capacity at 0.25–0.5 MiB for fixtures cumulatively
allocating 24–256 MiB. These are heap-capacity checks, not process peak RSS.

See the [integration report and evidence](../benchmarks/results/macos-arm64-2026-10-21-gc/REPORT.md)
and [current memory semantics](MEMORY.md). Earlier entries below describe their
historical source snapshots, including the former arena allocator.

## Self-hosted compiler — 2026-10-20

The compiler in `selfhost/compiler.gly` compiled its own source through three
generations on macOS arm64. Python produced stage 1; stage 1 produced stage 2;
stage 2 produced stage 3. Native build/check/run stages executed with an empty
search `PATH` and an absolute C-compiler path, so they could not find Python on
`PATH`. Stages 2 and 3 emitted byte-identical C, SHA-256
`eb218fa2f3986da937cd3dd7491ecdd195aced8284cd7fd3a858e683b2c0b55d`.

The native checking/emission regression run passed **all 40 tests without skips**,
including the real AppKit test. It performed 1,583 native source checks and 43
native C emissions, with 1,479 parser-rejection observations (including repeated
fixtures). Tests cover existing language semantics and safety checks, text and
systems operations, native CLI argument handling, Unicode/line-ending cases, and
source/output alias protection. The Python checker remains the differential
reference; native-emitted C supplies the runtime fixtures. The four new systems
tests also passed separately through the reference Python C emitter.

```sh
GLYPH_TEST_GUI=1 DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python selfhost/bootstrap.py --verify
```

A wheel containing the new systems runtime was built. The Python frontend from
that extracted wheel built the Glyph compiler, whose executable then checked its
own source. Formatting checks and `git diff --check` passed.

Artifacts: [bootstrap/test log](../selfhost/results/macos-arm64-2026-10-20/bootstrap.log),
[native corpus counts](../selfhost/results/macos-arm64-2026-10-20/corpus.json),
[source hashes, stage hashes and commands](../selfhost/results/macos-arm64-2026-10-20/verification.json),
[reference systems tests](../selfhost/results/macos-arm64-2026-10-20/systems-reference-tests.log),
and [packaging log](../selfhost/results/macos-arm64-2026-10-20/package.log).

This establishes a working self-hosting cycle and the recorded test coverage,
not correctness for all programs or a new performance result. Native formatting
remains in Python; POSIX build orchestration, a 1 MiB source limit and the existing
allocation arena are current boundaries. Linux and Windows bootstrap execution
have not been verified. See [usage and limitations](SELF_HOSTING.md).

## Native GUI library — 2026-10-20

All 33 tests passed without skips on macOS arm64 with the real AppKit desktop
test enabled:

```sh
GLYPH_TEST_GUI=1 DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m unittest discover -s tests -v
```

Five added test methods cover GUI signatures/reserved names, formatting and
optional backend selection, unsupported-platform diagnostics, calculator state,
native builds, source-located runtime errors, and real AppKit control actions,
keyboard equivalents, text updates, validation and window close/reopen cleanup.
The calculator state tests also cover decimals, sign entry, chained operations,
operator replacement, repeated equals, result entry, division by zero, large
results and clear recovery. GUI examples passed formatting checks.

The actual calculator window was also inspected and operated through the desktop
UI: multiplication displayed `42`, decimal addition displayed `3.75`, keyboard
division by zero displayed `Error`, and Clear recovered. This is correctness
evidence for the initial macOS backend, not cross-platform GUI support or a
performance measurement. The default test command skips the desktop test unless
`GLYPH_TEST_GUI=1`; GUI build/runtime tests require macOS.

Signed entry and the plus keyboard shortcut produced `-3` for `-5 + 2`, and the
`c` shortcut cleared the display. A wheel was built with the GUI Python module,
C headers and Objective-C source included; compiling the hello GUI using the
extracted wheel outside the source directory also succeeded.

## Value records and methods — 2026-10-20

All 28 test methods passed without skips on macOS arm64, using the same Command Line Tools SDK selection described below. The nine added record test methods cover privacy, construction, forward types, recursive-layout rejection, inference, malformed syntax, formatting, copy semantics, shared array fields, receiver evaluation order and checked runtime failures. Copy/composition and receiver-order fixtures execute at `-O0`, `-O2` and `-O3`; the `-O2` variants also execute formatted source.

The full suite includes all earlier native tests and seven runnable examples. The new record example also passed the CLI formatting check and `glyph run`, printing `25`, `32`, `5`, `3`, `7`. `git diff --check` passed.

Artifacts: [test log](../benchmarks/results/macos-arm64-2026-10-20-records/tests.log), [CLI output](../benchmarks/results/macos-arm64-2026-10-20-records/example.log), [source hashes and commands](../benchmarks/results/macos-arm64-2026-10-20-records/verification.json), and [record example](../examples/records.gly).

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python benchmarks/results/macos-arm64-2026-10-20-records/verify.py
```

This run verifies correctness, not new performance or AI-token savings. Records lower to C structs and statically called functions, but large value copies can still cost time. Array fields retain shared storage. Inheritance and interface dispatch are absent. Earlier benchmark results below describe their recorded source snapshots; the expanded agent guide has not been remeasured in this run. Cross-platform native execution remains pending.

## Inference and reduction implementation — 2026-10-20

Verified on macOS 26.5.2 arm64 with Python 3.14.7, Zig 0.14.1 / Clang 19.1.7, and the installed Command Line Tools SDK selected as below. The compiler/runtime changes are uncommitted; [run provenance](../benchmarks/results/macos-arm64-2026-10-20/verification.json) records the base revision and SHA-256 of the compiler, runtime, tests, benchmark programs, examples and supplied agent guide.

* All 19 test methods passed without skips. New tests cover aliases, forward and recursive inference, formatter stability, malformed reduction syntax, zip-length errors, source/body evaluation order, mutation and aliasing, empty reductions, floating-point order, and checked integer prefix sums at `-O0`, `-O2` and `-O3`.
* All nine authored task/language fixtures verified. Function source uses 49 AI BPE tokens in Glyph (9 sum, 16 count, 24 dot) versus Python's 47 (9, 16, 22), with `cl100k_base`. The original Glyph fixtures used 110. This is source-token accounting, not actual model sampling or billing. The updated supplied Glyph guide uses 532 tokens, so total AI task-cost parity is not established.
* The standard runtime suite passed five measured samples for each of 10 cases. LLVM inspection confirms the new fold and builtin sum share opcode counts; explicit loops retain checked scalar lowering.
* The focused reduction benchmark passed 15 measured samples for each of eight scenario/variant pairs. On small integers, builtin sum took a median 2.509 ms, fold 2.476 ms, the explicit checked Glyph loop 6.604 ms, and ordinary C 1.892 ms. This is about 2.6× faster than the checked loop, still about 33% slower than C. With alternating wide i64 values, sum took 6.591 ms versus the checked loop's 6.583 ms: the first-failure bailout avoided the earlier prototype's repeated-scan regression in this workload.

These are local measurements without controlled load, not a general performance guarantee. Cross-platform execution remains pending. Existing Windows and 2026-10-19 macOS evidence is preserved separately.

Artifacts: [report](../benchmarks/results/macos-arm64-2026-10-20/REPORT.md), [test log](../benchmarks/results/macos-arm64-2026-10-20/tests.log), [focused reduction measurements](../benchmarks/results/macos-arm64-2026-10-20/reductions.json), [raw AI-token observations](../benchmarks/results/macos-arm64-2026-10-20/agent.json). A runnable language example is [reductions.gly](../examples/reductions.gly).

Reproduce in an environment permitting process inspection:

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python benchmarks/results/macos-arm64-2026-10-20/verify.py
```

## Native verification on macOS

Date: 2026-10-19. macOS 26.5.2 arm64, Python 3.14.7, Zig 0.14.1 / Clang 19.1.7. Source revision: `6c62ba566e302ad29e084c98cb3b202ceada471b`; no compiler or runtime source changes were needed.

* All 10 test methods passed with no skips, including five native test methods covering examples, evaluation order/aliasing, runtime traps, CLI arguments/exit status, and 150 seeded differential arithmetic cases.
* All nine authored task/language fixtures executed and verified their outputs after the scripted repair.
* LLVM inspection found matching opcode counts for loop/fold reductions; the IR is not byte-identical.
* All 10 runtime cases completed one warmup and five measured processes (50 measured samples). Glyph and C native programs executed; workload checksums matched independent references.

The first attempt using Xcode's macOS 26.5 SDK failed to link standard C symbols. Selecting the existing Command Line Tools SDK (MacOSX14.4.sdk) via the per-command `DEVELOPER_DIR` environment variable resolved the failure. No system-wide developer selection or security setting was changed. Memory sampling required running the benchmark outside the Codex sandbox because macOS process enumeration via `sysctl` was denied there.

Reproduce after installing `.[bench]`, in an environment permitting process inspection:

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python benchmarks/results/macos-arm64-2026-10-19/verify.py
```

Results are preserved separately from the initial Windows observations: [report](../benchmarks/results/macos-arm64-2026-10-19/REPORT.md), [test log](../benchmarks/results/macos-arm64-2026-10-19/tests.log), [runtime measurements](../benchmarks/results/macos-arm64-2026-10-19/runtime.json), and [run provenance](../benchmarks/results/macos-arm64-2026-10-19/verification.json). The initial linker failure and sandbox benchmark failure are retained in that directory as well. Timings are local observations without controlled machine load. Linux/Windows native execution and actual sampled-agent efficiency remain unverified by this run.

## Initial Windows host (historical observations)

Date: 2026-10-19. Windows 11 x86-64, Python 3.12.14, Zig 0.14.1 / Clang 19.1.7.

Completed locally:

* Installed the editable Python package and generated the `glyph` entry point. `python -m glyph` runs frontend commands.
* Passed five frontend test methods, including 25 rejected-program cases, precise diagnostic span checks, CLI JSON/format checking, formatter round-trip/idempotence checks, and 500 seeded malformed-input cases.
* Compiled/linked all five example programs, the semantic/evaluation-order fixture, the runtime-trap fixture, a 150-case differential-arithmetic fixture, and the CLI entry/argument fixture. Runtime execution was explicitly skipped, not counted as a pass.
* Compiled/linked all Glyph and C benchmark programs and three task solutions per native language; collected actual diagnostics for deliberately invalid solutions.
* Inspected LLVM -O2 output for loop/fold i64 reduction. Both have the same instruction counts and checked-add primitive. SSA/phi ordering differs; no claim of identical IR bytes.
* Verified Python task-solution outputs and both Python benchmark workloads, recording five timed processes after warmup and independent checksum references.
* Recorded hardware, versions, compiler flags, compilation times, native executable sizes, source hashes, tokenizer and complete token/diagnostic observations.

Not verified:

* Execution of any generated Glyph or C native program; therefore native runtime correctness, timings and peak memory.
* Linux/macOS behavior. A Linux/Windows CI matrix is prepared but has not been dispatched locally.
* Actual agent retry counts, completion rates, or total billed/visible tokens per solved task. The available repair exercise is scripted, not an agent experiment.

The blocker is Microsoft Defender Exploit Guard rule `01443614-CD74-433A-B99E-2ECDC07BFC25`. The Windows Defender Operational log reported event 1121 blocking both Glyph-generated executables and a minimal C `int main(void) { return 0; }` program. Successful compilation is not proof of successful execution. No policy/security setting was altered.

The user selected an approved external runner; its location/access details are pending. On that runner, install the package and execute:

```sh
python -m pip install -e '.[bench]'
python -m unittest discover -s tests -v
python -m benchmarks.codegen
python -m benchmarks.agent
python -m benchmarks.runtime --samples 5
python -m benchmarks.report
```

Do not set `GLYPH_SKIP_EXECUTION` or pass `--skip-native-execution` on the approved runner. Preserve its report and raw JSON separately from the initial host's partial observations. If using GitHub Actions, the included workflow performs these steps and uploads results; it has not been claimed as run.


## Structured concurrency — 2026-10-27, macOS arm64

Both frontends pass the complete final corpus: **123 tests, two skips**, with
no failures or errors. The skips require Linux `/dev/full`. GUI integration was
enabled. The native run performs 1,754 native checks and 115 C emissions; see the
raw corpus report for authoritative counters. The three-stage generated-C fixed
point and native compilation with Python absent from PATH also pass.

The new tests exercise O0/O2/O3, 1/2/4 workers, numeric maps, scoped tasks and
bounded channels; they cover transitive safety checks, imports, generic functions,
methods, handle escapes, nested scopes, return cleanup, checked worker traps,
GC stress, FIFO/multiple producers, close wakeups and resource failures.
Condition-variable instrumentation proves simultaneous callback execution and
waiter states without timing sleeps. Injected pthread failures test task failure
and partial CPU-pool initialization/shutdown. A fatal-worker test verifies
that process termination bypasses atexit cleanup for main-owned resources.
Main-thread GUI/database operations
coexist with concurrency and retain their existing worker restrictions.

UBSan passes the collector and concurrency harness. ASan and TSan fail on empty
C control programs as well as the runtime on this host, so neither supplies
race/memory-safety evidence. The original sandbox-only service-test failures
were local-bind permission errors; the successful suites ran with local socket
access. No failure or skip was silently converted into a pass.

Linux x86-64 glibc cross-compilation succeeds but has not been executed here.
Windows concurrency produces G203; musl builds produce an explicit unsupported
collector-configuration diagnostic. Ordinary sequential platform paths remain.
A built wheel contains the concurrency runtime and threaded collector sources;
the native compiler built/ran the channel example from its extracted runtime
without Python on PATH.

Read the [delivery and benchmark report](../benchmarks/results/macos-arm64-2026-10-27-concurrency/REPORT.md),
[raw reference log](../benchmarks/results/macos-arm64-2026-10-27-concurrency/reference-tests.log),
[native fixed-point evidence](../selfhost/results/concurrency-macos-arm64-2026-10-27/verification.json),
and [native corpus](../selfhost/results/concurrency-macos-arm64-2026-10-27/corpus.json).
The compute-heavy case speeds up 3.42× at four workers; memory, tiny and
allocation-heavy cases expose limits. Source-token counts are authored-fixture
observations, not total agent-cost measurements.
