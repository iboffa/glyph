# Verification status on the initial host

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
