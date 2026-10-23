# Record performance and AI source-token measurements

Measured on 2026-10-20 (Europe/Vilnius), macOS arm64, Zig 0.14.1 / Clang 19.1.7. This measures the current working-tree compiler, including its newer standard-library and GUI support. [Raw results](records.json) preserve compiler/runtime source hashes, all measured samples, compiler commands, exact benchmark source, counted definitions and verification drivers. The compiler was not modified for this measurement.

## Native execution

Both languages use the same `-O2` backend, without fast-math, floating-point contraction, LTO or target tuning. One output-verified warmup precedes 15 samples per variant, with deterministically shuffled process order. Kernel clocks exclude allocation, setup, output and cleanup. No memory sampling or machine-load controls were used.

| Workload | Glyph median (range), ms | C median (range), ms | Glyph/C median |
|---|---:|---:|---:|
| Scalar Point: 6,000,000 mutating method calls | 5.514 (5.423–5.774) | 5.511 (5.438–5.707) | 1.001× |
| 100,000 nested Particle records, 60 update/reduction passes | 5.566 (5.466–5.737) | 5.522 (5.461–6.024) | 1.008× |

The observed medians differ by less than 1%, and the ranges overlap. These results are consistent with similar speed on these two workloads; they do not establish a statistically significant difference or general C-speed parity.

Point has two f64 fields and methods to move and calculate squared magnitude. Particle embeds a position and velocity Point, delegates movement to its position, and delegates squared magnitude. The scalar case prints its final magnitude; the array case accumulates each updated magnitude into a checksum. Runtime arguments determine workload sizes and seeds. Every warmup and measured output matches an independent reference computed with exact integer arithmetic in quarter units. The checksums keep the results observable. All 60 timed native outputs verified successfully.

These floating-point cases help isolate record layout and method dispatch from checked-integer arithmetic costs. Ordinary C omits Glyph's integer and bounds checks; the inputs stay inside the valid domain. This run does not measure large record copies, private factories, allocation-heavy workloads, polymorphism, memory use, Python runtime speed or other platforms.

The nine record correctness test methods also passed on this compiler snapshot, including copy/composition and receiver-order fixtures at `-O0`, `-O2`, and `-O3`. This was a focused record-suite run, not a rerun of the newer systems/GUI/self-hosting suites.

## AI source tokens

Counts use `tiktoken 0.12.0` with `cl100k_base`, the same fixed BPE encoding as earlier observations. These are authored source inventories, not language-lexer tokens, sampled model outputs or billing measurements. Python uses dataclasses, including the import, decorator and field annotations. C uses structs and ordinary functions.

| Fixture | Glyph definitions | Python definitions | C definitions | Glyph full source | Python full source | C full source |
|---|---:|---:|---:|---:|---:|---:|
| Point | 54 | 65 | 60 | 91 | 95 | 104 |
| Point + Particle | 94 | 112 | 114 | 158 | 166 | 190 |

Glyph uses about 17% and 16% fewer definition tokens than these Python fixtures. Including the executable verification driver narrows that to about 4% and 5%. The second fixture includes Point again; the rows are separate tasks and should not be added as independent definitions. All six task/language fixtures executed and produced the expected numeric outputs.

The tasks exercise construction and mutation. Python dataclass assignment retains reference semantics; these fixtures do not claim equivalent value-copy or receiver-snapshot behavior. Adding explicit Python copies for such tasks would change both source counts and runtime behavior. Other valid implementations or tokenizers could also change the comparison.

The current supplied Glyph agent guide costs another 1,007 tokens under this encoding. Actual prompts, model reasoning, retries, repeated context, task failure rates and billed tokens are unmeasured. Consequently these observations support concise source syntax, not a claim of lower total AI cost per correct task.

## Reproduce

From the project root with benchmark dependencies installed:

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m unittest discover -s tests -p test_records.py -v
DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m benchmarks.records --samples 15 --output path/to/new-record-results.json
```

The SDK selection is the existing macOS linking workaround. Use a new output path to preserve this snapshot. On other hosts, omit the macOS `DEVELOPER_DIR` override and use the local Python command. Generated C and inventory executables remain in `build/record_bench`. The runner rejects disabled native execution, unexpected outputs, nonpositive/nonfinite timings and compiler/runtime source changes during a run.
