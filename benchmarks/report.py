"""Generate a readable report from measured JSON; missing results stay missing."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results"


def main():
    agent = json.loads((OUT / "agent.json").read_text())
    runtime = json.loads((OUT / "runtime.json").read_text())
    meta = runtime["metadata"]
    lines = ["# Measured results", "", f"Date: {meta['date']}. Host: {meta['cpu']}; {meta['os']}; {meta['physical_cores']} physical / {meta['logical_cores']} logical cores; {meta['ram_bytes']/2**30:.1f} GiB RAM.", "",
             f"Python: `{meta['python'].splitlines()[0]}`. Zig: {meta['ziglang']}. Backend: `{meta['clang'].splitlines()[0]}`.", "", f"Flags: `{meta['flags']}`.", "",
             f"Native execution status: **{runtime['native_execution_status']}**.", "",
             "## Source token inventory", "", f"Tokenizer: `{agent['tokenizer']}`, tiktoken {agent['tiktoken']}. Same tokenizer, LF text and no chat framing for every language. Hand-authored function bodies, not shortest possible solutions or sampled agent completions.", "",
             "| Task | Glyph | Python | C |", "|---|---:|---:|---:|"]
    for task, languages in agent["tasks"].items():
        lines.append(f"| {task} | " + " | ".join(str(languages[l]["solution_tokens"]) for l in ["glyph", "python", "c"]) + " |")
    if (OUT / "codegen.json").exists():
        codegen = json.loads((OUT / "codegen.json").read_text())
        explanation = ("Fold and builtin sum use guarded reduction; explicit loops retain per-add checks."
                       if "sum_matches_fold_opcode_counts" in codegen else "The full IR differs in SSA/phi ordering.")
        lines += ["", "The [optimized LLVM inspection](codegen.json) found " + ("matching" if codegen["equal_opcode_counts"] else "different") + " instruction counts for explicit-loop and fold i64 reduction. " + explanation + " This is narrow structural evidence, not runtime verification or a general equivalence proof. Raw normalized functions: [loop](reduce_loop.ll.txt), [fold](reduce_fold.ll.txt)."]
    lines += ["", "Supplied language instruction tokens (not an established minimum): " + ", ".join(f"{k}: {v}" for k, v in agent["instruction_tokens"].items()) + ".", "",
              "## Scripted repair exercise", "", "One deliberately undefined name and one predetermined repair per task/language. These are harness retries, not measured agent retries. Visible totals include instructions, task, both full source attempts, diagnostic text and verified success feedback when available. Paths and native compiler notes are counted as emitted.", "",
              "| Task | Language | Full source tokens | Diagnostic tokens | Scripted retries | Visible transcript tokens | Verified correct |", "|---|---|---:|---:|---:|---:|---|"]
    for task, languages in agent["tasks"].items():
        for language, data in languages.items():
            lines.append(f"| {task} | {language} | {data['full_source_tokens']} | {data['diagnostic_tokens']} | {data['scripted_retries']} | {data['visible_transcript_tokens']} | {'yes' if data['verified'] else 'unverified'} |")
    lines += ["", "Actual agent retries and total tokens per correctly completed task: **not measured**. This exercise excludes model reasoning, tool-selection messages, retransmitted context and provider billing. It cannot establish agent cost savings. Glyph's guide is longer because it introduces a new language; pretrained familiarity with C/Python is not accounted for. Source counts describe these authored functions only, not general language efficiency.", "",
              "## Native compilation and executable size", "", "Three sequential compiles per program. Warm median uses the last two; first measurement includes whatever cache state existed (not a controlled cold build). Glyph includes frontend process startup; C invokes the compiler directly. Executable bytes exclude separate PDB symbols and the development toolchain. Python has no native executable artifact.", "",
              "| Program/language | Warm compile median (s) | First compile (s) | Executable bytes |", "|---|---:|---:|---:|"]
    for key, data in runtime["compilation"].items():
        if data["seconds"] is not None:
            lines.append(f"| {key} | {data['median_warm_s']:.4f} | {data['seconds'][0]:.4f} | {data['artifact_bytes']} |")
    lines += ["", "## Runtime", "", f"{runtime['samples']} measured processes per case after one warmup process; deterministic randomized language order. Kernel timings exclude process startup and array construction. Array reduction uses 200,000 elements × 100 passes; recurrence uses 200,000 steps × 5 passes. Inputs come from argv; every result is checked against an independent reference. Array contents change between passes and checksums are printed, preventing removal/hoisting of all useful work.", "",
              "| Program/language | Kernel median (ms) | Kernel min–max (ms) | Process median (ms) | Observed peak (MiB) |", "|---|---:|---:|---:|---:|"]
    for key, data in runtime["runs"].items():
        k = data.get("kernel_s")
        memory = data.get("peak_bytes")
        lines.append(f"| {key} | " + (f"{k['median']*1000:.3f} | {k['min']*1000:.3f}–{k['max']*1000:.3f}" if k else "n/a | n/a") + f" | {data['wall_s']['median']*1000:.3f} | " + (f"{memory['median']/2**20:.2f}" if memory else "unobserved") + " |")
    lines += ["", "Memory: " + meta["memory_method"] + ". Peaks cover the whole process, including array setup. Very short startup processes may escape observation. External timing includes the polling harness overhead; use internal kernel timings for computation comparisons. No CPU pinning, power/frequency control, or background-load isolation was applied. The host was used for other work; these are local observations.", "",
              "Python uses its built-in sum for the array workload, giving it a C-implemented reduction. C uses unchecked i64 arithmetic on the bounded benchmark domain; Glyph retains checks. Allocation/ownership models differ, and the arena retention tradeoff is not exercised by these bounded-allocation kernels. No I/O, service, concurrency or large application workload was measured. No general speedup or memory-efficiency claim follows from these results.", "",
              "Raw observations and exact diagnostics: [runtime.json](runtime.json), [agent.json](agent.json). Methodology: [../README.md](../README.md)."]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT / "REPORT.md")


if __name__ == "__main__":
    main()
