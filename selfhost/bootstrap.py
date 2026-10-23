"""Bootstrap and verify the native Glyph compiler; Python is stage 0 only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/selfhost')
    parser.add_argument('--cc', default=shutil.which('cc'))
    parser.add_argument('--verify', action='store_true', help='also run the language regression corpus through glyphc')
    args = parser.parse_args()
    if os.name == 'nt':
        parser.error('the initial native compiler process driver requires a POSIX host')
    if not args.cc:
        parser.error('put a C compiler on PATH or pass --cc /absolute/path/to/compiler')
    cc = Path(shutil.which(args.cc) or args.cc).resolve()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'selfhost/compiler.gly'
    runtime = ROOT / 'glyph'
    stages = [out / 'stage1', out / 'stage2', out / 'glyphc']
    records = []
    log = out / 'bootstrap.log'
    log.write_text('')

    def run(command, env=None):
        start = time.perf_counter()
        result = subprocess.run([str(a) for a in command], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=300)
        elapsed = time.perf_counter() - start
        records.append({'command': [str(a) for a in command], 'seconds': elapsed,
                        'returncode': result.returncode, 'python_on_path': env is None})
        with log.open('a') as stream:
            stream.write(json.dumps(records[-1]) + '\n' + result.stdout + result.stderr)
        if result.returncode:
            sys.stderr.write(result.stdout + result.stderr)
            raise RuntimeError(f'bootstrap command failed; see {log}')
        print(f'Completed {Path(str(command[0])).name}: {elapsed:.2f}s', flush=True)
        return result

    run([sys.executable, '-m', 'glyph', 'build', source, '-o', stages[0]])
    # No shell and no Python executable on PATH in either native generation.
    empty_path = out / 'empty-path'
    empty_path.mkdir(exist_ok=True)
    native_env = dict(os.environ, PATH=str(empty_path))
    for previous, current in zip(stages, stages[1:]):
        run([previous, 'build', source, '-o', current,
             '--runtime-dir', runtime, '--cc', cc], env=native_env)
    c2, c3 = Path(str(stages[1]) + '.c'), Path(str(stages[2]) + '.c')
    if c2.read_bytes() != c3.read_bytes():
        raise RuntimeError('stage 2 and stage 3 generated different C')
    run([stages[2], 'check', source], env=native_env)
    # Exercise the native driver's run command with an argument-bearing program.
    smoke = out / 'argument smoke.gly'
    smoke.write_text('main>void\n  print(concat("native: ", arg(0)))\n')
    smoke_result = run([stages[2], 'run', smoke, '-o', out / 'argument smoke',
                        '--runtime-dir', runtime, '--cc', cc, '--', 'no Python; spaces preserved'], env=native_env)
    if smoke_result.stdout != 'native: no Python; spaces preserved\n':
        raise RuntimeError('native driver argument/output verification failed')
    report = {
        'source': str(source), 'source_sha256': sha(source),
        'source_files_sha256': {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / 'selfhost').glob('*.gly'))},
        'runtime_sha256': {p.name: sha(p) for p in sorted(runtime.glob('*.h'))},
        'collector': json.loads((runtime / 'vendor/bdwgc/UPSTREAM.json').read_text()),
        'fixed_point': True, 'native_generations_without_python_on_path': True,
        'generated_c_sha256': sha(c3),
        'stages': {p.name: {'executable_sha256': sha(p), 'bytes': p.stat().st_size} for p in stages},
        'commands': records,
    }
    if args.verify:
        run([sys.executable, ROOT / 'selfhost/verify.py', stages[2], '--output-dir', out / 'corpus'])
        report['corpus'] = json.loads((out / 'corpus/report.json').read_text())
    (out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Fixed point verified. Native compiler: {stages[2]}')
    print(f'Verification: {out / "verification.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
