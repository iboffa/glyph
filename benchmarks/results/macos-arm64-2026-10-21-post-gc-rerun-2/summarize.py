"""Compare this rerun against the first production-GC benchmark."""
import hashlib
import json
from pathlib import Path
import re

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
PREVIOUS = OUT.parent / "macos-arm64-2026-10-21-post-gc"


def read(name, directory=OUT):
    return json.loads((directory / (name + ".json")).read_text())


verification = read("verification")
assert all(verification["steps"].get(key) == "passed" for key in
           ("tests", "codegen", "agent", "runtime", "reductions", "records", "memory", "report"))
assert not verification["source_changes_during_run"]
runtime, previous = read("runtime"), read("runtime", PREVIOUS)
memory, old_memory = read("memory"), read("memory", PREVIOUS)
records, reductions = read("records"), read("reductions")
tests = (OUT / "tests.log").read_text()
total = int(re.search(r"Ran (\d+) tests", tests).group(1))
skipped = len(re.findall(r"\.\.\. skipped ", tests))
counts = {name: sum(len(v[field]) for v in read(name)["runs"].values())
          for name, field in (("runtime", "measurements"), ("reductions", "seconds"),
                              ("records", "seconds"), ("memory", "measurements"))}
old_hashes = read("verification", PREVIOUS)["source_sha256"]
changed = [p for p, digest in verification["source_sha256"].items()
           if p in old_hashes and old_hashes[p] != digest]
added = [p for p in verification["source_sha256"] if p not in old_hashes
         and not p.startswith("benchmarks/results/")]
lines = ["# Production GC benchmark rerun — 2026-10-21", "",
         f"Completed {sum(counts.values())} verified timing samples: " + ", ".join(f"{v} {k}" for k,v in counts.items()) + ". Warmups are additional.", "",
         f"Correctness: {total-skipped} tests passed; {skipped} skipped (three self-hosted CLI tests because GLYPH_SELFHOST was not selected, and one write-failure test requiring /dev/full, unavailable on macOS). The AppKit lifecycle and forced-GC tests ran. Compiler/runtime source hashes remained unchanged throughout this run.", "",
         f"Run: {verification['started_at']} to {verification['finished_at']} (Europe/Vilnius).", "",
         "The current compiler includes changes since the first production-GC run, including collection/result support. These are separate working-tree snapshots with uncontrolled host load; differences cannot be attributed solely to GC or to a particular compiler change. Suites ran sequentially. Both runs use 15 samples per standard runtime, reduction and record case, plus five samples per allocation workload/scale.", "",
         "## Kernel comparison", "",
         "Median milliseconds; negative change means faster. The benchmark input source hashes match between runs.", "",
         "| Case | Previous | Rerun | Change |", "|---|---:|---:|---:|"]
for key, row in runtime["runs"].items():
    assert runtime["source_sha256"][key] == previous["source_sha256"][key], key
    if "kernel_s" not in row:
        continue
    old, new = previous["runs"][key]["kernel_s"]["median"], row["kernel_s"]["median"]
    lines.append(f"| {key} | {old*1000:.3f} | {new*1000:.3f} | {(new/old-1)*100:+.1f}% |")
lines += ["", "Kernel clocks exclude startup and setup/allocation; ordinary C omits Glyph's checked arithmetic. External process times and memory polling are preserved in the full report.", "",
          "## Focused kernels", "", "| Reduction | Fold (ms) | Sum (ms) | Checked loop (ms) | C (ms) |", "|---|---:|---:|---:|---:|"]
for scenario in ("small", "wide"):
    lines.append("| " + scenario + " | " + " | ".join(f'{reductions["runs"][scenario+"/"+v]["median_s"]*1000:.3f}' for v in ("fold", "sum", "loop", "c")) + " |")
lines += ["", "| Records | Glyph (ms) | C (ms) | Glyph/C |", "|---|---:|---:|---:|"]
for task in ("point", "particle"):
    g,c = (records["runs"][task+"/"+lang]["median_s"] for lang in ("glyph", "c"))
    lines.append(f"| {task} | {g*1000:.3f} | {c*1000:.3f} | {g/c:.3f}× |")
lines += ["", "## Allocation workloads", "",
          "4,096-batch medians. getrusage measures whole-process peak RSS. Batch p99 includes mutator and collector work, not isolated GC pauses. All three scales (512/2,048/4,096 batches) and retained-value checks are in memory.json. No forced collection occurs within timing.", "",
          "| Workload | Previous ms | Rerun ms | Previous peak MiB | Rerun peak MiB | Heap capacity MiB | Batch p99 ms |", "|---|---:|---:|---:|---:|---:|---:|"]
for task in ("numeric", "text", "cycles", "retained"):
    a,b = (d["runs"][task+"/8"]["medians"] for d in (old_memory,memory))
    lines.append(f'| {task} | {a["elapsed_s"]*1000:.3f} | {b["elapsed_s"]*1000:.3f} | {a["peak_rss_bytes"]/2**20:.2f} | {b["peak_rss_bytes"]/2**20:.2f} | {b["gc_heap_bytes"]/2**20:.3f} | {b["batch_p99_s"]*1000:.3f} |')
lines += ["", "## Startup and size", "", "| Metric | Previous Glyph | Rerun Glyph | Rerun C |", "|---|---:|---:|---:|"]
for label,fn in (("Empty process median (ms)", lambda d,k:d["runs"][k]["wall_s"]["median"]*1000),
                 ("Empty executable (bytes)", lambda d,k:d["compilation"][k]["artifact_bytes"]),
                 ("Warm empty-program compile (ms)", lambda d,k:d["compilation"][k]["median_warm_s"]*1000)):
    values=[fn(previous,"startup/glyph"),fn(runtime,"startup/glyph"),fn(runtime,"startup/c")]
    lines.append("| " + label + " | " + " | ".join(f"{v:,.3f}" if isinstance(v,float) else f"{v:,}" for v in values) + " |")
lines += ["", "Short process times include polling overhead. Compiler and collector caches were reused; these are not cold builds. No CPU affinity, power or load controls were applied.", "",
          "## Provenance", "", "Changed previously recorded sources: " + ", ".join(f"`{p}`" for p in changed) + ".", "",
          "New recorded sources: " + ", ".join(f"`{p}`" for p in added) + ".", "",
          "[Full runtime/token report](REPORT.md) · [runtime](runtime.json) · [reductions](reductions.json) · [records](records.json) · [allocation measurements](memory.json) · [tests](tests.log) · [source hashes](verification.json) · [frozen sources](source-snapshot.tar.gz).", "",
          "Source-token inventories measure authored fixtures, not actual AI reasoning, retries or billed task costs.", "",
          "Reproduce from the project root (copy the output directory first to preserve this run):", "", "```sh",
          f"GLYPH_TEST_GUI=1 DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python {OUT.relative_to(ROOT)}/run.py",
          f".venv/bin/python {OUT.relative_to(ROOT)}/summarize.py", "```"]
(OUT / "COMPARISON.md").write_text("\n".join(lines)+"\n")
path=OUT/"REPORT.md"
path.write_text(path.read_text().replace("the arena retention tradeoff is not exercised by these bounded-allocation kernels", "GC reclamation is measured separately in [the allocation workloads](COMPARISON.md#allocation-workloads)").replace("[../README.md](../README.md)", "[methodology](../../README.md)"))
verification["tests"]={"run":total,"passed":total-skipped,"skipped":skipped}
verification["timing_sample_counts"]=counts
verification["reporting_source_sha256"]={str(Path(__file__).relative_to(ROOT)):hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(OUT/"verification.json").write_text(json.dumps(verification,indent=2)+"\n")
print(OUT/"COMPARISON.md")
