"""Reproducible concurrency measurements; checks every output, preserves raw runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

from glyph.backend import Emitter, compile_c
from glyph.checker import check
from glyph.syntax import parse
from .runtime import ROOT, metadata


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--samples', type=int, default=5)
    ap.add_argument('--output-dir', type=Path, default=ROOT / 'benchmarks/results/macos-arm64-2026-10-27-concurrency')
    opts = ap.parse_args()
    if opts.samples < 3:
        ap.error('at least three samples required')
    out = opts.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    frozen = out / 'sources'
    frozen.mkdir(exist_ok=True)
    build = ROOT / 'build/concurrency-bench'
    build.mkdir(parents=True, exist_ok=True)
    programs = ROOT / 'benchmarks/programs/concurrency'
    commands, expected, sources, builds = {}, {}, {}, {}
    shared = ['runtime.h', 'std_runtime.h', 'concurrency_runtime.h']

    def c_prefix(threaded):
        return ('#define GLYPH_CONCURRENCY 1\n' if threaded else '') + '#define GLYPH_GC 1\n#define G_FILE_JSON "\\\"benchmark\\\""\n' + ''.join('#include "' + str(ROOT / 'glyph' / h) + '"\n' for h in shared[:3 if threaded else 2])

    def add(name, source, language, arguments, checksum, workers=1, threaded=False):
        key = name + '/' + language + '/' + str(workers)
        base = build / key.replace('/', '_')
        sources[key] = source
        suffix = '.gly' if language.startswith('glyph') else '.c'
        original = frozen / (base.name + suffix)
        original.write_text(source)
        c = base.with_suffix('.c')
        c.write_text(Emitter().emit(check(parse(source)), str(original)) if suffix == '.gly' else c_prefix(threaded) + source)
        start = time.perf_counter()
        flags = compile_c(c, base)
        builds[key] = {'seconds': time.perf_counter() - start, 'bytes': base.stat().st_size,
                       'command': flags, 'source_sha256': hashlib.sha256(source.encode()).hexdigest()}
        commands[key] = ([str(base)] + list(map(str, arguments)), workers)
        expected[key] = checksum

    glyph_template = (programs / 'transform.gly').read_text()
    c_template = (programs / 'transform.c').read_text()
    def compute(x):
        x += 1
        for _ in range(64):
            x = x * 48271 % 2147483647
        return x
    for workload, n, repeats in [('compute', 20000, 3), ('memory', 500000, 5), ('tiny', 32, 3000), ('allocation', 5000, 3)]:
        gly, c, reference = glyph_template, c_template, compute
        if workload in {'memory', 'tiny'}:
            gly = 'transform x:int>int = x + 1\n' + gly[gly.index('sequential a:'):]
            a, b = c.index('static int64_t transform'), c.index('static void chunk')
            c = c[:a] + 'static int64_t transform(int64_t x) { return g_add(x,1,1,1); }\n' + c[b:]
            reference = lambda x: x + 1
        if workload == 'allocation':
            gly = 'transform x:int>int = len(concat("value:", str_i64(x)))\n' + gly[gly.index('sequential a:'):]
            a, b = c.index('static int64_t transform'), c.index('static void chunk')
            c = c[:a] + 'static int64_t transform(int64_t x) { return g_std_concat((g_str){"value:",6},g_std_str_i64(x,1,1),1,1).len; }\n' + c[b:]
            reference = lambda x: len('value:' + str(x))
        checksum = reference(repeats - 1) + sum(reference(i) for i in range(1, n))
        for workers in (1, 2, 4):
            add(workload, gly, 'glyph_parallel', [n, repeats], checksum, workers)
            add(workload, c.replace('RUN_MAP', 'g_par_map(input,sizeof(int64_t),chunk,NULL,1,1)').replace('SHUTDOWN', 'g_concurrency_shutdown();'), 'c_parallel', [n, repeats], checksum, workers, True)
        sequential_glyph = gly.replace('par_map(input, transform)', 'sequential(input)')
        add(workload, sequential_glyph, 'glyph_sequential', [n, repeats], checksum)
        add(workload, c.replace('RUN_MAP', 'sequential(input)').replace('SHUTDOWN', ''), 'c_sequential', [n, repeats], checksum)
        if workload == 'memory':
            baseline_source = frozen / 'baseline_sequential.gly'
            baseline_source.write_text(sequential_glyph)
    for workload, n in [('tasks', 1000), ('channel', 20000), ('latency', 1000)]:
        for language in ('glyph', 'c'):
            source = (programs / (workload + ('.gly' if language == 'glyph' else '.c'))).read_text()
            checksum = n * 42 if workload == 'tasks' else n * (n - 1) // 2 if workload == 'channel' else n
            add(workload, source, language, [n], checksum, threaded=True)
    for language in ('glyph', 'c'):
        source = (programs / ('allocate.gly' if language == 'glyph' else 'allocate.c')).read_text()
        add('allocation_only', source, language, [500000, 20], 500000)
    for workers in (1, 2, 4):
        key = 'compute/python_processes/' + str(workers)
        commands[key] = ([sys.executable, str(programs / 'transform.py'), '20000', '3', str(workers)], workers)
        expected[key] = compute(2) + sum(compute(i) for i in range(1, 20000))
        sources[key] = (programs / 'transform.py').read_text()
    add('startup', 'main>void\n  ret\n', 'glyph', [], None)
    add('startup', 'int main(void) { return 0; }\n', 'c', [], None)

    report = {'metadata': metadata(), 'samples': opts.samples, 'warmups_per_case': 1,
              'date': '2026-10-27', 'builds': builds, 'runs': {}, 'expected': expected,
              'method': 'Transform: first dispatch separately, then repeated steady-state calls including fresh output allocation. Auxiliary tasks/channels: internal total, including thread creation. Wall time includes process start/setup/cleanup. No memory sampling. C uses the same checked arithmetic, GC, and scheduler as Glyph; isolates frontend/lowering overhead, not an independent C scheduler. Python uses persistent ProcessPoolExecutor with chunksize=256; first includes process startup, steady includes serialization.'}
    report['metadata']['memory_method'] = 'Not sampled in this benchmark.'
    report['metadata']['timing_method'] = report['method']
    try:
        report['metadata']['cpu_model'] = subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    def run(key):
        cmd, workers = commands[key]
        env = dict(os.environ, GLYPH_WORKERS=str(workers), GLYPH_GC_STRESS='0')
        start = time.perf_counter()
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120, check=True)
        elapsed = time.perf_counter() - start
        lines = proc.stdout.splitlines()
        if expected[key] is not None and (not lines or int(lines[0]) != expected[key]):
            raise AssertionError((key, proc.stdout, expected[key]))
        return {'wall_s': elapsed, 'stdout': proc.stdout, 'first_s': float(lines[1]) if len(lines) == 3 else None,
                'steady_s': float(lines[-1]) if lines else None}
    for key in commands:
        run(key)
        report['runs'][key] = {'command': commands[key][0], 'workers': commands[key][1], 'observations': []}
    rng = random.Random(27)
    for sample in range(opts.samples):
        order = list(commands)
        rng.shuffle(order)
        for key in order:
            report['runs'][key]['observations'].append(run(key))
        print('Verified sample', sample + 1, flush=True)
    for data in report['runs'].values():
        observations = data['observations']
        data['median_wall_s'] = statistics.median(x['wall_s'] for x in observations)
        data['median_steady_s'] = statistics.median(x['steady_s'] for x in observations) if observations[0]['steady_s'] is not None else None
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(ROOT / '.tmp/tiktoken'))
    import tiktoken
    encoding = tiktoken.get_encoding('cl100k_base')
    report['tokens'] = {'encoding': 'cl100k_base', 'tiktoken': tiktoken.__version__,
                        'application': {key: len(encoding.encode(source)) for key, source in sources.items()},
                        'c_shared_support': {h: len(encoding.encode((ROOT / 'glyph' / h).read_text())) for h in shared},
                        'note': 'Application counts include driver; C imports bundled runtime support counted separately. These are source-token counts, not total agent-cost measurements.'}
    report['runtime_sha256'] = {h: hashlib.sha256((ROOT / 'glyph' / h).read_bytes()).hexdigest() for h in shared}
    (out / 'benchmarks.json').write_text(json.dumps(report, indent=2) + '\n')
    print(out / 'benchmarks.json')


if __name__ == '__main__':
    main()
