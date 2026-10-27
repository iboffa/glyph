"""Auxiliary concurrency evidence: sanitizers and pre-change sequential comparisons."""
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import time

from glyph.gc_support import collector_flags, VENDOR
from .runtime import ROOT


def main():
    out = ROOT / 'benchmarks/results/macos-arm64-2026-10-27-concurrency'
    build = ROOT / 'build/concurrency-bench'
    env = dict(os.environ, DEVELOPER_DIR='/Library/Developer/CommandLineTools')
    evidence = {'baseline_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), 'sanitizers': {}}
    for sanitizer in ('address,undefined', 'thread'):
        name = sanitizer.replace(',', '-')
        exe = build / ('sanitizer-' + name)
        cmd = ['/usr/bin/clang', str(ROOT / 'tests/concurrency_runtime_harness.c'), str(VENDOR / 'extra/gc.c'),
               '-o', str(exe), '-g', '-fno-omit-frame-pointer', '-fsanitize=' + sanitizer] + collector_flags(threaded=True)
        compiled = subprocess.run(cmd, capture_output=True, text=True, env=env)
        record = {'command': cmd, 'build_returncode': compiled.returncode, 'build_stderr': compiled.stderr}
        if compiled.returncode == 0:
            try:
                result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30,
                                        env=dict(env, GLYPH_GC_STRESS='1'))
                record.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
            except subprocess.TimeoutExpired as exc:
                record.update(timeout_seconds=30, stderr=str(exc.stderr))
        evidence['sanitizers'][sanitizer] = record
        (out / ('sanitizer-' + name + '.log')).write_text(json.dumps(record, indent=2) + '\n')
    commands = {
        'previous_startup': [str(build / 'baseline_startup')],
        'current_startup': [str(build / 'startup_glyph_1')],
        'previous_memory': [str(build / 'baseline_memory'), '500000', '5'],
        'current_memory': [str(build / 'memory_glyph_sequential_1'), '500000', '5'],
    }
    measurements = {key: {'command': cmd, 'binary_bytes': Path(cmd[0]).stat().st_size, 'samples': []} for key, cmd in commands.items()}
    def sample(key):
        start = time.perf_counter()
        result = subprocess.run(commands[key], capture_output=True, text=True, env=env, check=True, timeout=30)
        elapsed = time.perf_counter() - start
        lines = result.stdout.splitlines()
        if 'memory' in key and int(lines[0]) != 125000250004:
            raise AssertionError((key, result.stdout))
        return {'wall_s': elapsed, 'stdout': result.stdout, 'steady_s': float(lines[-1]) if lines else None}
    for key in commands:
        sample(key)
    rng = random.Random(27)
    for _ in range(15):
        keys = list(commands)
        rng.shuffle(keys)
        for key in keys:
            measurements[key]['samples'].append(sample(key))
    for item in measurements.values():
        item['median_wall_s'] = statistics.median(x['wall_s'] for x in item['samples'])
        if item['samples'][0]['steady_s'] is not None:
            item['median_steady_s'] = statistics.median(x['steady_s'] for x in item['samples'])
    evidence['sequential_regression'] = {'warmups': 1, 'samples': 15, 'observations': measurements,
                                        'baseline_method': 'git archive HEAD glyph into build/concurrency-baseline; compile with that package as cwd using the same Python and Zig toolchain.'}
    try:
        evidence['cpu_model'] = subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        evidence['cpu_model'] = None
    (out / 'auxiliary-validation.json').write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    main()
