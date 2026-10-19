# Measured results

Date: 2026-10-19. Host: AMD Ryzen 7 PRO 5850U with Radeon Graphics; Windows-11-10.0.26200-SP0; 8 physical / 16 logical cores; 11.8 GiB RAM.

Python: `3.12.14 (main, Aug 25 2026, 14:01:42) [MSC v.1944 64 bit (AMD64)]`. Zig: 0.14.1. Backend: `clang version 19.1.7 (https://github.com/ziglang/zig-bootstrap de1b01a8c1dddf75a560123ac1c2ab182b4830da)`.

Flags: `-std=c11 -O2 -fno-fast-math -ffp-contract=off; no LTO; default target; no stripping`.

Native execution status: **blocked by host policy; native timings and peak memory unmeasured**.

## Source token inventory

Tokenizer: `cl100k_base`, tiktoken 0.12.0. Same tokenizer, LF text and no chat framing for every language. Hand-authored function bodies, not shortest possible solutions or sampled agent completions.

| Task | Glyph | Python | C |
|---|---:|---:|---:|
| sum | 14 | 9 | 53 |
| positive_count | 39 | 16 | 59 |
| dot | 57 | 22 | 64 |

The [optimized LLVM inspection](codegen.json) found matching instruction counts for explicit-loop and fold i64 reduction. The full IR differs in SSA/phi ordering. This is narrow structural evidence, not runtime verification or a general equivalence proof. Raw normalized functions: [loop](reduce_loop.ll.txt), [fold](reduce_fold.ll.txt).

Supplied language instruction tokens (not an established minimum): glyph: 455, c: 62, python: 36.

## Scripted repair exercise

One deliberately undefined name and one predetermined repair per task/language. These are harness retries, not measured agent retries. Visible totals include instructions, task, both full source attempts, diagnostic text and verified success feedback when available. Paths and native compiler notes are counted as emitted.

| Task | Language | Full source tokens | Diagnostic tokens | Scripted retries | Visible transcript tokens | Verified correct |
|---|---|---:|---:|---:|---:|---|
| sum | glyph | 37 | 94 | 1 | 665 | unverified |
| sum | python | 26 | 82 | 1 | 218 | yes |
| sum | c | 112 | 127 | 1 | 455 | unverified |
| positive_count | glyph | 65 | 95 | 1 | 719 | unverified |
| positive_count | python | 36 | 86 | 1 | 239 | yes |
| positive_count | c | 121 | 131 | 1 | 474 | unverified |
| dot | glyph | 90 | 94 | 1 | 783 | unverified |
| dot | python | 49 | 91 | 1 | 285 | yes |
| dot | c | 139 | 144 | 1 | 538 | unverified |

Actual agent retries and total tokens per correctly completed task: **not measured**. This exercise excludes model reasoning, tool-selection messages, retransmitted context and provider billing. It cannot establish agent cost savings. Glyph's guide is longer because it introduces a new language; pretrained familiarity with C/Python is not accounted for. Glyph is smaller than these C implementations but larger than Python on these three functions.

## Native compilation and executable size

Three sequential compiles per program. Warm median uses the last two; first measurement includes whatever cache state existed (not a controlled cold build). Glyph includes frontend process startup; C invokes the compiler directly. Executable bytes exclude separate PDB symbols and the development toolchain. Python has no native executable artifact.

| Program/language | Warm compile median (s) | First compile (s) | Executable bytes |
|---|---:|---:|---:|
| startup/glyph | 0.9132 | 0.9323 | 179200 |
| startup/c | 0.3898 | 0.4272 | 179200 |
| array/glyph | 0.8482 | 0.9389 | 182784 |
| array/c | 0.4503 | 0.4668 | 180736 |
| array_loop/glyph | 0.7157 | 0.7121 | 182784 |
| recurrence/glyph | 0.8844 | 0.6507 | 180736 |
| recurrence/c | 0.4612 | 0.4722 | 180736 |

## Runtime

5 measured processes per case after one warmup process; deterministic randomized language order. Kernel timings exclude process startup and array construction. Array reduction uses 200,000 elements × 100 passes; recurrence uses 200,000 steps × 5 passes. Inputs come from argv; every result is checked against an independent reference. Array contents change between passes and checksums are printed, preventing removal/hoisting of all useful work.

| Program/language | Kernel median (ms) | Kernel min–max (ms) | Process median (ms) | Observed peak (MiB) |
|---|---:|---:|---:|---:|
| startup/python | n/a | n/a | 247.949 | 16.88 |
| array/python | 261.270 | 200.987–290.353 | 592.200 | 25.07 |
| recurrence/python | 300.730 | 216.135–400.918 | 579.091 | 17.49 |

Memory: sum of process-tree RSS/working sets sampled every 1ms, including Python launcher children; maximum observed sum is a lower bound; null if unobserved. Peaks cover the whole process, including array setup. Very short startup processes may escape observation. External timing includes the polling harness overhead; use internal kernel timings for computation comparisons. No CPU pinning, power/frequency control, or background-load isolation was applied. The host was used for other work; these are local observations.

Python uses its built-in sum for the array workload, giving it a C-implemented reduction. C uses unchecked i64 arithmetic on the bounded benchmark domain; Glyph retains checks. Allocation/ownership models differ, and the arena retention tradeoff is not exercised by these bounded-allocation kernels. No I/O, service, concurrency or large application workload was measured. No general speedup or memory-efficiency claim follows from these results.

Raw observations and exact diagnostics: [runtime.json](runtime.json), [agent.json](agent.json). Methodology: [../README.md](../README.md).
