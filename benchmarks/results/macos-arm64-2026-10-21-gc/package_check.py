import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

root = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file())
out = root / 'build/gc-wheel-check'
out.mkdir(exist_ok=True)
wheel = next((root / 'build/gc-wheel').glob('*.whl'))
with zipfile.ZipFile(wheel) as archive:
    archive.extractall(out)
vendor = out / 'glyph/vendor/bdwgc'
manifest = json.loads((vendor / 'UPSTREAM.json').read_text())
for name, sha in manifest['files_sha256'].items():
    assert hashlib.sha256((vendor / name).read_bytes()).hexdigest() == sha, name
print(f"All {len(manifest['files_sha256'])} upstream files present and verified", flush=True)
program = out / 'packaged.gly'
program.write_text('main>void\n  print(sum(fill(1000, 7)))\n  print(concat("bundled-", "gc"))\n')
env = dict(os.environ, PYTHONPATH=str(out), GLYPH_CACHE_DIR=str(out / 'fresh-cache'))
commands = [
    [sys.executable, '-m', 'glyph', 'run', str(program), '-o', str(out / 'console')],
    [sys.executable, '-m', 'glyph', 'build', str(root / 'examples/gui_hello.gly'), '-o', str(out / 'gui')],
    [str(root / 'build/selfhost-gc/glyphc'), 'run', str(program), '-o', str(out / 'native-driver'), '--runtime-dir', str(out / 'glyph')],
]
for command in commands:
    proc = subprocess.run(command, cwd=out, env=env, capture_output=True, text=True)
    print(json.dumps({'command': command, 'returncode': proc.returncode}), flush=True)
    print(proc.stdout + proc.stderr, flush=True)
    assert proc.returncode == 0
    if 'run' in command:
        assert proc.stdout == '7000\nbundled-gc\n'
print('Wheel console execution, GUI build and native driver with packaged runtime passed', flush=True)
