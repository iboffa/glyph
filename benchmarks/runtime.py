"""Reproducible local measurements. Run with python -m benchmarks.runtime."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
import psutil
from glyph.backend import compile_c, compiler

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ROOT / "benchmarks" / "programs"
OUT = ROOT / "benchmarks" / "results"
BUILD = ROOT / "build" / "bench"


def measure(command):
    start = time.perf_counter()
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    observed, peak = 0, 0
    try:
        process = psutil.Process(proc.pid)
        while proc.poll() is None:
            try:
                # Windows venv python.exe can be a launcher with a child interpreter.
                # Measure the process tree, not just that small launcher.
                rss = 0
                for member in [process, *process.children(recursive=True)]:
                    try:
                        rss += member.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                peak = max(peak, rss)
                observed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            time.sleep(.001)
    finally:
        stdout, stderr = proc.communicate(timeout=120)
    elapsed = time.perf_counter() - start
    if proc.returncode:
        raise RuntimeError(f"{command}: {stderr.decode(errors='replace')}")
    return {"wall_s": elapsed, "peak_bytes": peak or None, "memory_samples": observed,
            "stdout": stdout.decode().strip()}


def metadata():
    cpu = platform.processor()
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    return {"date": time.strftime("%Y-%m-%d"), "os": platform.platform(), "cpu": cpu,
            "physical_cores": psutil.cpu_count(logical=False), "logical_cores": psutil.cpu_count(),
            "ram_bytes": psutil.virtual_memory().total, "python": sys.version,
            "ziglang": importlib.metadata.version("ziglang"),
            "clang": subprocess.check_output(compiler() + ["--version"], text=True).strip(),
            "flags": "-std=c11 -O2 -fno-fast-math -ffp-contract=off; no LTO; default target; no stripping",
            "memory_method": "sum of process-tree RSS/working sets sampled every 1ms, including Python launcher children; maximum observed sum is a lower bound; null if unobserved",
            "timing_method": "internal monotonic wall clock for kernel; external perf_counter includes setup/output/cleanup and monitoring; separate empty-process startup"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--skip-native-execution", action="store_true", help="record compilation and Python only; never invent native results")
    args = parser.parse_args()
    if args.samples < 3:
        parser.error("at least 3 samples required")
    BUILD.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"metadata": metadata(), "samples": args.samples, "compilation": {}, "runs": {}, "source_sha256": {}}
    commands = {}
    # Same array workload, with the imperative spelling substituted for fold.
    loop = PROGRAMS.joinpath("array.gly").read_text().replace("sum a:[i64]>i64 = fold a 0 +", "sum a:[i64]>i64\n  s:i64 = 0\n  for x:a\n    s += x\n  ret s")
    loop_path = BUILD / "array_loop.gly"
    loop_path.write_text(loop)
    for task in ["startup", "array", "array_loop", "recurrence"]:
        for lang in (["glyph"] if task == "array_loop" else ["glyph", "c", "python"]):
            key = task + "/" + lang
            suffix = {"glyph": ".gly", "c": ".c", "python": ".py"}[lang]
            src = loop_path if task == "array_loop" else PROGRAMS / (task + suffix)
            report["source_sha256"][key] = hashlib.sha256(src.read_bytes()).hexdigest()
            output = BUILD / (task + "_" + lang + (".exe" if os.name == "nt" else ""))
            if lang == "python":
                commands[key] = [sys.executable, str(src)]
                report["compilation"][key] = {"seconds": None, "artifact_bytes": None, "source_bytes": src.stat().st_size, "note": "interpreted; parsing included in process wall time; no native artifact"}
            else:
                times = []
                for _ in range(3):
                    start = time.perf_counter()
                    if lang == "glyph":
                        subprocess.run([sys.executable, "-m", "glyph", "build", str(src), "-o", str(output)], check=True, cwd=ROOT)
                    else:
                        compile_c(src, output)
                    times.append(time.perf_counter() - start)
                commands[key] = [str(output)]
                report["compilation"][key] = {"seconds": times, "median_warm_s": statistics.median(times[1:]), "artifact_bytes": output.stat().st_size}
            print("built", key, flush=True)
    cases = {"startup": [], "array": [200000, 100, 37], "array_loop": [200000, 100, 37], "recurrence": [200000, 5, 37]}
    # Independent references, outside all timing regions.
    a = [(i*17+37)%1000 for i in range(200000)]
    expected_array = 0
    for r in range(100):
        a[r%len(a)] = (a[r%len(a)]+r)%1000
        expected_array += sum(a)
    x = 37
    for _ in range(1000000):
        x = x*48271%2147483647
    expected = {"startup": None, "array": expected_array, "array_loop": expected_array, "recurrence": x}
    order = [key for key in commands if not args.skip_native_execution or key.endswith("/python")]
    report["native_execution_status"] = "blocked by host policy; native timings and peak memory unmeasured" if args.skip_native_execution else "executed and output verified"
    for key in order:
        task = key.split("/")[0]
        measure(commands[key] + list(map(str, cases[task])))  # warmup process
        report["runs"][key] = {"arguments": cases[task], "expected": expected[task], "measurements": []}
    rng = random.Random(20261019)
    for trial in range(args.samples):
        rng.shuffle(order)
        for key in order:
            task = key.split("/")[0]
            row = measure(commands[key] + list(map(str, cases[task])))
            if task != "startup":
                value, elapsed = row["stdout"].splitlines()
                if int(value) != expected[task]:
                    raise AssertionError((key, value, expected[task]))
                row["kernel_s"] = float(elapsed)
            report["runs"][key]["measurements"].append(row)
        print("verified trial", trial + 1, flush=True)
    for data in report["runs"].values():
        rows = data["measurements"]
        for metric in ["wall_s", "kernel_s", "peak_bytes"]:
            values = [r[metric] for r in rows if r.get(metric) is not None]
            if values:
                data[metric] = {"median": statistics.median(values), "min": min(values), "max": max(values)}
    (OUT / "runtime.json").write_text(json.dumps(report, indent=2) + "\n")
    print("saved", OUT / "runtime.json")


if __name__ == "__main__":
    main()
