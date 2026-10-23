# Measured results

Date: 2026-10-19. Host: arm; macOS-26.5.2-arm64-arm-64bit-Mach-O; 8 physical / 8 logical cores; 8.0 GiB RAM.

Python: `3.14.7 (v3.14.7:823f0323ee6, Aug  5 2026, 07:07:01) [Clang 21.0.0 (clang-2100.1.1.101)]`. Zig: 0.14.1. Backend: `clang version 19.1.7 (https://github.com/ziglang/zig-bootstrap de1b01a8c1dddf75a560123ac1c2ab182b4830da)`.

Flags: `-std=c11 -O2 -fno-fast-math -ffp-contract=off; no LTO; default target; no stripping`.

Native execution status: **executed and output verified**.

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
| sum | glyph | 37 | 74 | 1 | 651 | yes |
| sum | python | 26 | 62 | 1 | 198 | yes |
| sum | c | 112 | 107 | 1 | 441 | yes |
| positive_count | glyph | 65 | 75 | 1 | 705 | yes |
| positive_count | python | 36 | 66 | 1 | 219 | yes |
| positive_count | c | 121 | 111 | 1 | 460 | yes |
| dot | glyph | 90 | 74 | 1 | 769 | yes |
| dot | python | 49 | 71 | 1 | 265 | yes |
| dot | c | 139 | 124 | 1 | 524 | yes |

Actual agent retries and total tokens per correctly completed task: **not measured**. This exercise excludes model reasoning, tool-selection messages, retransmitted context and provider billing. It cannot establish agent cost savings. Glyph's guide is longer because it introduces a new language; pretrained familiarity with C/Python is not accounted for. Glyph is smaller than these C implementations but larger than Python on these three functions.

## Native compilation and executable size

Three sequential compiles per program. Warm median uses the last two; first measurement includes whatever cache state existed (not a controlled cold build). Glyph includes frontend process startup; C invokes the compiler directly. Executable bytes exclude separate PDB symbols and the development toolchain. Python has no native executable artifact.

| Program/language | Warm compile median (s) | First compile (s) | Executable bytes |
|---|---:|---:|---:|
| startup/glyph | 0.1610 | 0.1935 | 50000 |
| startup/c | 0.0969 | 0.0950 | 49944 |
| array/glyph | 0.1595 | 0.1872 | 51256 |
| array/c | 0.1113 | 0.0940 | 50344 |
| array_loop/glyph | 0.1655 | 0.1746 | 51264 |
| recurrence/glyph | 0.1677 | 0.1577 | 50752 |
| recurrence/c | 0.0953 | 0.1103 | 50208 |

## Runtime

5 measured processes per case after one warmup process; deterministic randomized language order. Kernel timings exclude process startup and array construction. Array reduction uses 200,000 elements × 100 passes; recurrence uses 200,000 steps × 5 passes. Inputs come from argv; every result is checked against an independent reference. Array contents change between passes and checksums are printed, preventing removal/hoisting of all useful work.

| Program/language | Kernel median (ms) | Kernel min–max (ms) | Process median (ms) | Observed peak (MiB) |
|---|---:|---:|---:|---:|
| startup/glyph | n/a | n/a | 7.198 | unobserved |
| startup/c | n/a | n/a | 7.099 | unobserved |
| startup/python | n/a | n/a | 36.904 | 16.52 |
| array/glyph | 9.611 | 9.175–10.156 | 20.480 | 2.83 |
| array/c | 2.706 | 2.478–3.621 | 8.233 | 2.83 |
| array/python | 120.075 | 118.860–136.948 | 172.466 | 23.25 |
| array_loop/glyph | 9.236 | 8.825–10.959 | 19.678 | 2.83 |
| recurrence/glyph | 5.460 | 5.442–5.922 | 13.672 | 1.27 |
| recurrence/c | 5.510 | 5.424–6.183 | 13.706 | 1.27 |
| recurrence/python | 140.633 | 137.668–143.720 | 180.317 | 16.92 |

Memory: sum of process-tree RSS/working sets sampled every 1ms, including Python launcher children; maximum observed sum is a lower bound; null if unobserved. Peaks cover the whole process, including array setup. Very short startup processes may escape observation. External timing includes the polling harness overhead; use internal kernel timings for computation comparisons. No CPU pinning, power/frequency control, or background-load isolation was applied. The host was used for other work; these are local observations.

Python uses its built-in sum for the array workload, giving it a C-implemented reduction. C uses unchecked i64 arithmetic on the bounded benchmark domain; Glyph retains checks. Allocation/ownership models differ, and the arena retention tradeoff is not exercised by these bounded-allocation kernels. No I/O, service, concurrency or large application workload was measured. No general speedup or memory-efficiency claim follows from these results.

Raw observations and exact diagnostics: [runtime.json](runtime.json), [agent.json](agent.json). Methodology: [methodology](../../README.md).
