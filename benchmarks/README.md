# Benchmark methodology

The [second 2026-10-21 production-GC run](results/macos-arm64-2026-10-21-post-gc-rerun-2/COMPARISON.md) repeats the same 390 timing samples on the newer compiler snapshot. It records 68 passing tests and four skips, and compares directly with the first run. Glyph and C kernel times both fell about 29%; allocation peak RSS stayed near 2.45–3.66 MiB. Source changes and raw observations are preserved with the report.

The [2026-10-21 production-GC benchmark](results/macos-arm64-2026-10-21-post-gc/COMPARISON.md) reruns runtime, reduction, record and allocation workloads with the integrated collector: 390 verified timing samples, 54 passing correctness tests and three self-hosted CLI tests skipped. It preserves raw data, source hashes and frozen sources separately from the earlier runs. Historical comparisons include contemporary C measurements to expose session-to-session timing variation.

The [2026-10-21 memory experiment](results/macos-arm64-2026-10-21-memory/REPORT.md) compares the former arena allocator, scoped batch cleanup and two tracing-GC variants on temporary arrays, strings, cycles and retained values. It includes forced-collection safety tests, 225 verified timing samples, process peak memory, batch latency and frozen sources. The original experiment is preserved in its source snapshot. Glyph now uses the measured atomic-allocation GC strategy by default; see [memory management](../docs/MEMORY.md). Run the historical four-way comparison from that snapshot, since it rewrites the old arena runtime.

The two dimensions below must not be combined into a single claim of language superiority. The initial Windows host can compile PE executables but an IT-managed Defender rule blocks their execution. Its reports therefore include only source tokens, compiler diagnostics, native compilation/size and Python execution. A separate [macOS arm64 run](results/macos-arm64-2026-10-19/REPORT.md) completed native tests and five measured trials on 2026-10-19; see [verification setup](../docs/VERIFICATION.md#native-verification-on-macos). The scripts fail on incorrect outputs; they do not fill missing metrics with estimates.

The [2026-10-20 report](results/macos-arm64-2026-10-20/REPORT.md) measures the implemented inference and fused-reduction syntax. Its [focused reduction data](results/macos-arm64-2026-10-20/reductions.json) also covers the guarded-sum fast path and wide-i64 fallback; [verification notes](../docs/VERIFICATION.md) explain the results and reproducible command.

The separate [record measurements](results/macos-arm64-2026-10-20-record-measurements/REPORT.md) compare scalar and nested-array record kernels against C, plus verified authored record definitions against Python dataclasses and C structs. Run `python -m benchmarks.records --samples 15 --output path/to/records.json`. This uses internal kernel timing without memory sampling. It reports definition and full-program BPE token counts separately; Python reference semantics and unmeasured total AI task costs remain explicit limitations.

Run from the project root after `pip install -e '.[bench]'`:

```sh
python -m unittest discover -s tests -v
python -m benchmarks.agent
python -m benchmarks.runtime --samples 5
python -m benchmarks.report
```

For the restricted initial host only, add `--skip-native-execution` to both benchmark commands. This explicitly records unverified native results. See [the generated report](results/REPORT.md), [raw runtime measurements](results/runtime.json) and [raw token/diagnostic inventory](results/agent.json). Do not mix reports from different hosts; preserve their JSON together.

## Agent efficiency

All comparisons use `tiktoken==0.12.0`, encoding `cl100k_base`. This is a fixed BPE tokenizer, not a claim about a particular deployed coding model's tokenizer. The first use downloads tokenizer vocabulary data; the cache is `.tmp/tiktoken`. We count the same UTF-8/LF source representations for Glyph, C and Python, and report characters separately to avoid confusing characters with tokens.

Three tasks exercise sum, counting positives and dot product. Function-only tokens exclude test drivers; full source tokens include executable verification drivers. Equivalent inputs and expected outputs are supplied for all languages. Idiomatic Python builtins and Glyph reductions are permitted. The 2026-10-20 fixtures use inferred expression results, the int alias and fused reductions; earlier saved results retain the original source. C uses a pointer plus explicit length. Functions operate in the same non-overflowing test domain. These implementations are authored fixtures, not best-of-N optimized golfing submissions.

The instruction cost is the **supplied** guide/rubric, not a proven minimum. Glyph uses `docs/AGENT_GUIDE.md`; C/Python receive short familiar-language instructions recorded in the raw transcript. Neither instruction length nor task source length measures pretrained familiarity, repair reliability or agent planning effort.

The diagnostic exercise inserts one undefined function call, collects actual compiler/runtime diagnostics, restores the authored correct source, and verifies its output when execution is permitted. It records one scripted retry by construction. Visible cost is the sum of tokenizer counts of instructions + task + complete failed source + diagnostic + complete corrected source + verification feedback. The raw records preserve every counted event. For an unexecuted native task, verified correctness and cost per verified task are null. There is no agent behind this exercise, so actual agent retries and actual total task cost remain null in all local results.

To run a real agent study: use matched tasks, one fixed model/version, independent fresh contexts per language/task/seed, identical tool budgets and stopping criteria, and withheld correctness tests. Supply the guides, record every request/response/tool result and all attempts, and include failed tasks in the cost numerator. Use several problem families and repeated seeds; report completion rate and uncertainty, not just mean tokens among successes. Provider billing (including reasoning and cached-input distinctions) is separate from visible text retokenization.

`python -m benchmarks.score_transcripts trials.jsonl` scores externally recorded real attempts. Each line has `task`, `language`, `model`, Boolean `success`, nonnegative `retries`, `events:[{kind,text}]`, and optional `billed_total_tokens`. Include repeated history if it was resent. The scorer computes total visible tokens across successes **and failures**, divided by successful tasks, plus success counts/retries. It cannot verify omitted transcript events or the correctness labels; those must come from the study harness. Missing provider billing remains null.

## Runtime efficiency

`runtime.py` records hardware, OS, Python, Zig and Clang versions, flags, exact inputs, source SHA-256, all samples, output checks, executable byte sizes, and compilation times. Python is interpreted and has no comparable native artifact; parsing is included in process duration. Native sizes exclude PDB sidecars/development dependencies.

Both native languages compile through the same Zig Clang/LLVM with `-std=c11 -O2 -fno-fast-math -ffp-contract=off`; no LTO, stripping, native-CPU tuning or profile-guided optimization. The C baseline omits overflow/bounds checks inside kernels but benchmark inputs are mathematically bounded. Glyph retains its language-mandated checks. Generated source and compiler intermediates remain in `build/bench`.

Workloads:

* **Array reduction:** construct 200,000 runtime-dependent integer values. Each of 100 timed passes changes one element and sums the array, accumulating a printed checksum. This prevents the sum being hoisted unchanged out of the repetition loop. Separate Glyph fold and explicit-loop spellings are built. Python uses built-in `sum`, a competitive baseline. Input generation/allocation is outside kernel timing but included in whole-process duration and memory.
* **Integer recurrence:** run `x = x * 48271 % 2147483647` for 200,000 steps × 5 passes. The seed is a runtime argument and the final x is printed. The dependency chain prevents dead-work elimination. It is a narrow scalar-integer workload, not a proxy for all native execution.
* **Startup:** a separate empty main / Python `pass` program. Measure external process launch-to-exit independently rather than subtracting two noisy measurements.

One warmup process precedes five measured processes by default. Language/workload order is deterministically shuffled each round. Within-process kernel clocks are QueryPerformanceCounter on Windows and CLOCK_MONOTONIC on POSIX, with Python perf_counter. The timed region includes repeated work and excludes setup/output/cleanup. It approximates steady-state throughput; there is no JIT or adaptive runtime warmup, and early cache effects remain. Every measured output is checked against independent Python references outside timing.

Memory uses the maximum observed sum of process-tree RSS/working sets sampled every millisecond. This includes the child interpreter created by the Windows venv launcher, avoiding the false result of measuring only the tiny launcher. Sampling can underestimate the true peak; missing observations are null. Shared pages may be counted more than once between processes. The peak includes startup, interpreter and setup arrays. Whole-process durations include polling overhead. Separate memory-only runs would improve isolation in a larger study.

Three sequential compiles per native case measure build wall time; the final two give a warm median. The first compile has uncontrolled existing cache state and is **not** labeled cold. Zig's initial libc compilation can dominate a new cache. Glyph invokes a Python frontend subprocess while C invokes the backend directly; this reflects CLI compilation cost, not only backend time.

This initial suite does not control power management, CPU affinity, background load, machine temperature or antivirus scanning. It does not measure allocation-heavy services, real compiler tasks, file I/O, concurrency or end-to-end agent completion. Report medians and ranges, preserve raw data, and expand workload coverage before generalizing.

`python -m benchmarks.reductions --samples 15 --output path/to/reductions.json` additionally compares integer fold, builtin sum, an explicit checked Glyph loop and ordinary C on the same array workload. It repeats the comparison with alternating values near ±2^40, which force the guarded reduction to stop speculating and use its scalar suffix. All variants mutate one element between passes; an independent Python reference reproduces truncating integer remainder and verifies each output. Results include every internal kernel timing, source hashes and toolchain metadata. This focused benchmark does not sample memory. It tests both benefit and fallback cost; fast small-integer results must not be generalized to arbitrary i64 or floating-point inputs.

## Structured concurrency

`python -m benchmarks.concurrency --samples 5` measures numeric compute,
bandwidth, tiny transforms, concurrent allocation, scoped task creation/join,
channel throughput and blocking round trips. It compares sequential Glyph/C,
1/2/4-worker Glyph/C and a CPU-parallel Python process pool. C shares the checked
runtime/scheduler to isolate frontend costs; this is not an independent optimized
C scheduler. First dispatch, steady execution, allocation-only work and process
startup are reported separately, with independently checked outputs and raw
samples. See the [2026-10-27 report](results/macos-arm64-2026-10-27-concurrency/REPORT.md)
for hardware, token counts, sanitizer limits and pre-change sequential comparisons.

## Allocation controls and compiler/release comparison

The [2026-10-28 report](results/macos-arm64-2026-10-28-memory/REPORT.md) includes
a frozen starting revision, allocation-heavy kernels and aliases/escapes, retained
slices, cycles, closure allocation, parallel scaling, explicit storage domains,
self-hosted compilation, PGO/LTO and isolated collector experiments. Run
`python -m benchmarks.memory_suite --baseline build/memory-baseline --samples 7`
after bootstrapping both compilers as shown in that report. Timings run sequentially
across suites; instrumented collector/memory runs are separate. Raw observations,
source hashes, precise inputs, and superseded preliminary data are retained.
`python -m benchmarks.memory_report` regenerates the comparison from those results.
