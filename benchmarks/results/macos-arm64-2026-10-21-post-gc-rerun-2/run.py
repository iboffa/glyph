"""Rerun production-GC benchmarks without overwriting historical results."""
import contextlib
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tarfile
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def now():
    return datetime.now(ZoneInfo("Europe/Vilnius")).isoformat()


def memory():
    from benchmarks.memory import HARNESS, replace_function
    from benchmarks.memory_cases import CASES
    from benchmarks.runtime import metadata
    from glyph.backend import Emitter, compile_c
    from glyph.checker import check
    from glyph.syntax import parse

    build = ROOT / "build/post-gc-memory"
    build.mkdir(parents=True, exist_ok=True)
    # Reuse the historical timing/RSS harness, with no allocator rewriting.
    harness = replace_function(HARNESS, "region_end", lambda old: "")
    harness = harness.replace("INIT", "g_gc_init();")
    harness = harness.replace(" atexit(g_cleanup);", "")
    harness = harness.replace("        g_alloc *mark = g_allocations;\n", "")
    harness = harness.replace("        RELEASE\n", "")
    harness = harness.replace("#if BENCH_GC", "#if 1")
    harness = harness.replace('\\\"requested_bytes\\\"', '\\\"gc_total_allocated_bytes\\\"')
    harness = harness.replace(',\\\"allocations\\\":%llu', '')
    harness = harness.replace("(unsigned long long)bench_requested", "(unsigned long long)GC_get_total_bytes()")
    harness = harness.replace("(unsigned long long)bench_allocations, ", "")
    report = {"metadata": metadata(), "samples": 5, "scales": [1, 4, 8],
              "method": "Unmodified production Emitter/runtime and bundled collector; fresh process; one verified warmup; shuffled order; automatic collection during timed work; per-batch latency includes mutator and GC, not isolated GC pauses; getrusage peak RSS before final forced collection; GC byte counts include allocator overhead.",
              "compilation": {}, "runs": {}}
    commands = {}
    for task, case in CASES.items():
        generated = Emitter().emit(check(parse(case["source"])), task + ".gly")
        generated = generated[:generated.index("int main(int argc, char **argv) {")]
        if sys.platform == "darwin":
            generated = "#define _DARWIN_C_SOURCE\n" + generated
        driver = harness.replace("SETUP", "g_array keep = f_setup();" if task == "retained" else "")
        driver = driver.replace("WORK", "f_work(i, keep)" if task == "retained" else "f_work(i)")
        driver = driver.replace("VALIDATE", "f_validate(keep)" if task == "retained" else "0")
        source = build / (task + ".c")
        source.write_text(generated + driver)
        (OUT / (task + ".gly")).write_text(case["source"])
        (OUT / (task + ".c")).write_text(generated + driver)
        exe = build / task
        report["compilation"][task] = {"command": compile_c(source, exe), "generated_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        commands[task] = str(exe)

    def run(task, scale):
        n = 512 * scale
        proc = subprocess.run([commands[task], str(n)], capture_output=True, text=True, check=True, timeout=60)
        row = json.loads(proc.stdout)
        assert row["checksum"] == CASES[task]["expected"](n), (task, row)
        assert row["retained"] == (2 * sum(range(n - 32, n)) if task == "retained" else 0), (task, row)
        assert row["elapsed_s"] > 0 and row["peak_rss_bytes"] > 0, row
        return row

    order = [(task, scale) for task in CASES for scale in report["scales"]]
    for task, scale in order:
        run(task, scale)
        report["runs"][f"{task}/{scale}"] = {"batches": 512 * scale, "measurements": []}
    rng = random.Random(20261021)
    for trial in range(report["samples"]):
        rng.shuffle(order)
        for task, scale in order:
            report["runs"][f"{task}/{scale}"]["measurements"].append(run(task, scale))
        print("verified production memory trial", trial + 1, flush=True)
    for data in report["runs"].values():
        data["medians"] = {field: statistics.median(row[field] for row in data["measurements"]) for field in data["measurements"][0]}
    (OUT / "memory.json").write_text(json.dumps(report, indent=2) + "\n")


def main():
    assert os.environ.get("GLYPH_SKIP_EXECUTION") != "1"
    assert os.environ.get("GLYPH_GC_STRESS") != "1", "Do not force collections in timing runs"
    inputs = [p for folder in ("glyph", "tests", "benchmarks/programs") for p in (ROOT / folder).rglob("*")
              if p.is_file() and "__pycache__" not in p.parts]
    inputs += list((ROOT / "benchmarks").glob("*.py"))
    inputs += [ROOT / "docs/AGENT_GUIDE.md", ROOT / "pyproject.toml", Path(__file__)]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    record = {"started_at": now(), "base_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "source_sha256": hashes, "developer_dir": os.environ.get("DEVELOPER_DIR"), "steps": {}}
    (OUT / "verification.json").write_text(json.dumps(record, indent=2) + "\n")
    with tarfile.open(OUT / "source-snapshot.tar.gz", "w:gz") as archive:
        for path in hashes:
            archive.add(ROOT / path, arcname=path)
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    with (OUT / "tests.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    record["steps"]["tests"] = "passed"
    print((OUT / "tests.log").read_text(), flush=True)
    for name in ("codegen", "agent", "runtime", "reductions", "records", "memory", "report"):
        print("Running", name, flush=True)
        with (OUT / (name + ".log")).open("w") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            if name == "memory":
                memory()
            else:
                module = importlib.import_module("benchmarks." + name)
                module.OUT = OUT
                sys.argv = ["benchmarks." + name]
                if name == "runtime":
                    sys.argv += ["--samples", "15"]
                elif name in ("reductions", "records"):
                    sys.argv += ["--samples", "15", "--output", str(OUT / (name + ".json"))]
                module.main()
        record["steps"][name] = "passed"
        print((OUT / (name + ".log")).read_text(), flush=True)
        (OUT / "verification.json").write_text(json.dumps(record, indent=2) + "\n")
    record["source_changes_during_run"] = [p for p, digest in hashes.items() if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != digest]
    record["finished_at"] = now()
    (OUT / "verification.json").write_text(json.dumps(record, indent=2) + "\n")
    assert not record["source_changes_during_run"]


if __name__ == "__main__":
    main()
