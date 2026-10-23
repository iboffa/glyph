"""Verified record kernels versus C, plus authored AI source-token inventories."""
import argparse
from datetime import datetime
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
from zoneinfo import ZoneInfo

import tiktoken
from glyph.backend import Emitter, compile_c, compiler
from glyph.checker import check
from glyph.syntax import parse

ROOT = Path(__file__).resolve().parents[1]
POINT = {
    "glyph": """type Point
  x:f64
  y:f64
  norm2 = self.x * self.x + self.y * self.y
  mut move dx:f64, dy:f64>void
    self.x += dx
    self.y += dy
""",
    "python": """from dataclasses import dataclass

@dataclass
class Point:
    x: float
    y: float

    def norm2(self):
        return self.x * self.x + self.y * self.y

    def move(self, dx, dy):
        self.x += dx
        self.y += dy
""",
    "c": """typedef struct { double x, y; } Point;
static double norm2(Point p) { return p.x * p.x + p.y * p.y; }
static void move(Point *p, double dx, double dy) { p->x += dx; p->y += dy; }
""",
}
PARTICLE = {
    "glyph": """type Particle
  position:Point
  velocity:Point
  norm2 = self.position.norm2()
  mut step>void
    self.position.move(self.velocity.x, self.velocity.y)
""",
    "python": """@dataclass
class Particle:
    position: Point
    velocity: Point

    def norm2(self):
        return self.position.norm2()

    def step(self):
        self.position.move(self.velocity.x, self.velocity.y)
""",
    "c": """typedef struct { Point position, velocity; } Particle;
static double particle_norm2(Particle p) { return norm2(p.position); }
static void step(Particle *p) { move(&p->position, p->velocity.x, p->velocity.y); }
""",
}
GLYPH_MAIN = {
    "point": """main>void
  n := argi(0)
  seed := f64(argi(1))
  p := Point(seed, seed)
  start := clock()
  i := 0
  while i < n
    p.move(0.25, 0.5)
    i += 1
  result := p.norm2()
  elapsed := clock() - start
  print(result)
  print(elapsed)
""",
    "particle": """main>void
  n := argi(0)
  repeats := argi(1)
  seed := argi(2)
  a := fill(n, Particle(Point(0.0, 0.0), Point(0.25, 0.5)))
  i := 0
  while i < n
    a[i].position = Point(f64(i % 97 + seed), f64(i % 89 + seed))
    i += 1
  checksum := 0.0
  start := clock()
  r := 0
  while r < repeats
    i = 0
    while i < n
      a[i].step()
      checksum += a[i].norm2()
      i += 1
    r += 1
  elapsed := clock() - start
  print(checksum)
  print(elapsed)
""",
}
C_MAIN = {
    "point": """int main(int argc, char **argv) {
    if (argc != 3) return 2;
    int64_t n = strtoll(argv[1], 0, 10);
    double seed = strtoll(argv[2], 0, 10);
    Point p = {seed, seed};
    double start = now();
    for (int64_t i = 0; i < n; ++i) move(&p, 0.25, 0.5);
    double result = norm2(p), elapsed = now() - start;
    printf("%.17g\\n%.17g\\n", result, elapsed);
    return 0;
}
""",
    "particle": """int main(int argc, char **argv) {
    if (argc != 4) return 2;
    int64_t n = strtoll(argv[1], 0, 10), repeats = strtoll(argv[2], 0, 10);
    int64_t seed = strtoll(argv[3], 0, 10);
    Particle *a = malloc((size_t)n * sizeof(*a));
    if (!a) return 3;
    for (int64_t i = 0; i < n; ++i)
        a[i] = (Particle){{(double)(i % 97 + seed), (double)(i % 89 + seed)}, {0.25, 0.5}};
    double checksum = 0, start = now();
    for (int64_t r = 0; r < repeats; ++r)
        for (int64_t i = 0; i < n; ++i) { step(&a[i]); checksum += particle_norm2(a[i]); }
    double elapsed = now() - start;
    printf("%.17g\\n%.17g\\n", checksum, elapsed);
    free(a);
    return 0;
}
""",
}


def reference(task, args):
    # Exact integer arithmetic in quarter units, independent of measured code.
    if task == "point":
        n, seed = args
        return ((4 * seed + n) ** 2 + (4 * seed + 2 * n) ** 2) / 16
    n, repeats, seed = args
    sx = sum(4 * (i % 97 + seed) for i in range(n))
    sy = sum(4 * (i % 89 + seed) for i in range(n))
    squares = sum((4 * (i % 97 + seed)) ** 2 + (4 * (i % 89 + seed)) ** 2 for i in range(n))
    numerator = repeats * squares + (2 * sx + 4 * sy) * repeats * (repeats + 1) // 2
    numerator += 5 * n * repeats * (repeats + 1) * (2 * repeats + 1) // 6
    assert numerator < 2**53  # All positive quarter-unit products/sums are exact binary64.
    return numerator / 16


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/results/records.json")
    args = parser.parse_args()
    if args.samples < 3:
        parser.error("at least three samples required")
    if os.environ.get("GLYPH_SKIP_EXECUTION") == "1":
        parser.error("record measurements require native execution")
    build = ROOT / "build" / "record_bench"
    build.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(ROOT / ".tmp/tiktoken"))
    encoder = tiktoken.get_encoding("cl100k_base")
    count = lambda source: len(encoder.encode(source, disallowed_special=()))
    cases = {"point": [6000000, 37], "particle": [100000, 60, 37]}
    inputs = [p for p in (ROOT / "glyph").iterdir() if p.suffix in {".py", ".h", ".m"}]
    inputs += [Path(__file__), ROOT / "benchmarks/programs/common.h", ROOT / "docs/AGENT_GUIDE.md"]
    hashes = {str(p.resolve().relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    report = {
        "started_at": datetime.now(ZoneInfo("Europe/Vilnius")).isoformat(),
        "metadata": {"platform": platform.platform(), "python": sys.version,
                     "ziglang": importlib.metadata.version("ziglang"),
                     "clang": subprocess.check_output(compiler() + ["--version"], text=True).strip(),
                     "developer_dir": os.environ.get("DEVELOPER_DIR"),
                     "sdk": subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip() if sys.platform == "darwin" else None},
        "source_sha256": hashes, "samples": args.samples, "cases": cases,
        "method": "One verified warmup per variant; randomized process order; internal kernel clocks; setup/output/cleanup excluded; same -O2 backend without fast-math or FP contraction; no memory sampling.",
        "limits": "Two f64 workloads; ordinary C omits Glyph bounds/integer checks; no controlled machine load. Token counts are authored BPE source inventories, not billed AI tokens or sampled-agent costs. Python dataclasses use reference semantics; these tasks exercise construction and mutation, not record assignment/copy or receiver-snapshot equivalence.",
        "tokenizer": "cl100k_base", "tiktoken": importlib.metadata.version("tiktoken"),
        "glyph_guide_tokens": count((ROOT / "docs/AGENT_GUIDE.md").read_text()),
        "actual_total_agent_tokens_per_correct_task": None,
        "inventory": {}, "compilation": {}, "runs": {},
    }
    commands = {}
    common = (ROOT / "benchmarks/programs/common.h").read_text()
    for task in cases:
        report["inventory"][task] = {}
        for language in ("glyph", "python", "c"):
            definition = POINT[language] + ("\n" + PARTICLE[language] if task == "particle" else "")
            # Verify the counted definitions with the same construction/mutation task.
            if language == "glyph":
                driver = "main>void\n  p := Point(3.0, 4.0)\n  p.move(1.0, 2.0)\n  print(p.norm2())\n"
                if task == "particle":
                    driver += "  q := Particle(p, Point(0.25, 0.5))\n  q.step()\n  print(q.norm2())\n"
            elif language == "python":
                driver = "p = Point(3.0, 4.0)\np.move(1.0, 2.0)\nprint(p.norm2())\n"
                if task == "particle":
                    driver += "q = Particle(p, Point(0.25, 0.5))\nq.step()\nprint(q.norm2())\n"
            else:
                driver = 'int main(void) { Point p = {3, 4}; move(&p, 1, 2); printf("%.17g\\n", norm2(p));\n'
                if task == "particle":
                    driver += 'Particle q = {p, {0.25, 0.5}}; step(&q); printf("%.17g\\n", particle_norm2(q));\n'
                driver += "return 0; }\n"
            source = ("#include <stdio.h>\n" if language == "c" else "") + definition + "\n" + driver
            base = build / f"inventory_{task}_{language}"
            if language == "python":
                path = base.with_suffix(".py")
                path.write_text(source)
                command = [sys.executable, str(path)]
            else:
                path = base.with_suffix(".c")
                path.write_text(Emitter().emit(check(parse(source))) if language == "glyph" else source)
                exe = base.with_suffix(".exe")
                compile_c(path, exe)
                command = [str(exe)]
            actual = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
            expected = [52.0, 60.3125] if task == "particle" else [52.0]
            assert list(map(float, actual.stdout.splitlines())) == expected, actual.stdout
            report["inventory"][task][language] = {"definition_tokens": count(definition), "full_source_tokens": count(source), "definition": definition, "full_source": source, "verified": True, "stdout": actual.stdout}
        for language in ("glyph", "c"):
            key = task + "/" + language
            definition = POINT[language] + (PARTICLE[language] if task == "particle" else "")
            source = definition + GLYPH_MAIN[task] if language == "glyph" else common + definition + C_MAIN[task]
            base = build / (task + "_" + language)
            path = base.with_suffix(".c")
            generated = Emitter().emit(check(parse(source)), task + ".gly") if language == "glyph" else source
            path.write_text(generated)
            exe = base.with_suffix(".exe")
            command = compile_c(path, exe)
            report["compilation"][key] = {"command": command, "source": source, "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "generated_c_sha256": hashlib.sha256(generated.encode()).hexdigest()}
            commands[key] = [str(exe), *map(str, cases[task])]

    expected = {task: reference(task, values) for task, values in cases.items()}
    def run(key):
        proc = subprocess.run(commands[key], capture_output=True, text=True, timeout=60, check=True)
        value, elapsed = map(float, proc.stdout.splitlines())
        assert value == expected[key.split("/")[0]], (key, value, expected)
        assert math.isfinite(elapsed) and elapsed > 0, (key, elapsed)
        return elapsed

    measurements = {key: [] for key in commands}
    for key in commands:
        run(key)
    rng = random.Random(20261020)
    order = list(commands)
    for trial in range(args.samples):
        rng.shuffle(order)
        for key in order:
            measurements[key].append(run(key))
        print("verified record trial", trial + 1, flush=True)
    for key, rows in measurements.items():
        report["runs"][key] = {"seconds": rows, "median_s": statistics.median(rows), "min_s": min(rows), "max_s": max(rows), "expected": expected[key.split("/")[0]]}
    for path, digest in hashes.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, "Source changed during run: " + path
    report["finished_at"] = datetime.now(ZoneInfo("Europe/Vilnius")).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for key, result in report["runs"].items():
        print(f"{key}: {result['median_s'] * 1000:.3f} ms")
    for task, languages in report["inventory"].items():
        print(task, {lang: result["definition_tokens"] for lang, result in languages.items()})
    print("saved", args.output)


if __name__ == "__main__":
    main()
