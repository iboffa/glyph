"""Compare guarded sums with checked loops and C, including the wide-i64 fallback."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics
import subprocess

from glyph.backend import Emitter, compile_c
from glyph.checker import check
from glyph.syntax import parse
from .runtime import ROOT, metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/results/reductions.json")
    args = parser.parse_args()
    if args.samples < 3:
        parser.error("at least 3 samples required")
    build = ROOT / "build" / "reductions"
    build.mkdir(parents=True, exist_ok=True)
    glyph = (ROOT / "benchmarks/programs/array.gly").read_text()
    c = (ROOT / "benchmarks/programs/array.c").read_text().replace(
        '#include "common.h"', '#include "../../benchmarks/programs/common.h"')
    header = "sum a:[i64]>i64 = fold a 0 +"
    loop = "sum a:[i64]>i64\n  s:i64 = 0\n  for x:a\n    s += x\n  ret s"
    commands, hashes, expected = {}, {}, {}
    n, repeats, seed = 200000, 100, 37
    for scenario in ["small", "wide"]:
        gly_source, c_source = glyph, c
        if scenario == "wide":
            gly_source = glyph.replace(
                "    a[i] = (i * 17 + seed) % 1000",
                "    if i % 2 == 0\n      a[i] = 1099511627776 + seed\n"
                "    else\n      a[i] = -1099511627776 + seed")
            c_source = c.replace(
                "a[i]=(i*17+seed)%1000",
                "a[i]=(i%2==0 ? INT64_C(1099511627776) : -INT64_C(1099511627776))+seed")
        sources = {
            "fold": gly_source,
            "sum": gly_source.replace(header, "reduce a:[int] = sum(a)").replace(
                "checksum += sum(a)", "checksum += reduce(a)"),
            "loop": gly_source.replace(header, loop),
            "c": c_source,
        }
        for variant, source in sources.items():
            key = scenario + "/" + variant
            base = build / (scenario + "_" + variant)
            original = base.with_suffix(".c" if variant == "c" else ".gly")
            original.write_text(source)
            hashes[key] = hashlib.sha256(source.encode()).hexdigest()
            c_path = base.with_suffix(".c")
            if variant != "c":
                c_path.write_text(Emitter().emit(check(parse(source)), str(original)))
            exe = base.with_suffix(".exe")
            compile_c(c_path, exe)
            commands[key] = [str(exe), str(n), str(repeats), str(seed)]
        values = ([(i * 17 + seed) % 1000 for i in range(n)] if scenario == "small" else
                  [(1 << 40 if i % 2 == 0 else -(1 << 40)) + seed for i in range(n)])
        checksum = 0
        for r in range(repeats):
            value = values[r % n] + r
            # Glyph and C remainder truncate toward zero; Python % does not.
            quotient = abs(value) // 1000 * (-1 if value < 0 else 1)
            values[r % n] = value - quotient * 1000
            checksum += sum(values)
        expected[scenario] = checksum

    def run(key):
        proc = subprocess.run(commands[key], capture_output=True, text=True, timeout=30, check=True)
        value, elapsed = proc.stdout.splitlines()
        if int(value) != expected[key.split("/")[0]]:
            raise AssertionError((key, proc.stdout, expected))
        return float(elapsed)

    measurements = {key: [] for key in commands}
    for key in commands:
        run(key)
    rng = random.Random(20261020)
    order = list(commands)
    for _ in range(args.samples):
        rng.shuffle(order)
        for key in order:
            measurements[key].append(run(key))
    report = {
        "metadata": metadata(), "arguments": [n, repeats, seed],
        "method": "one warmup; randomized process order; verified outputs; internal kernel clocks",
        "source_sha256": hashes, "expected": expected, "samples": args.samples,
        "runs": {key: {"seconds": rows, "median_s": statistics.median(rows),
                       "min_s": min(rows), "max_s": max(rows)} for key, rows in measurements.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for key, row in report["runs"].items():
        print(f"{key}: {row['median_s'] * 1000:.3f} ms")
    print("saved", args.output)


if __name__ == "__main__":
    main()
