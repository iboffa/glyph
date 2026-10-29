"""Package source overlays, release profiles and hashes for the memory report."""
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'benchmarks/results/macos-arm64-2026-10-28-memory'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    paths = subprocess.check_output(
        ['git', 'ls-files', '--modified', '--others', '--exclude-standard', '-z'],
        cwd=ROOT).decode().split('\0')
    sources = sorted({p for p in paths if p and (ROOT / p).is_file()
                      and not p.startswith('benchmarks/results/')
                      and Path(p).name != '.DS_Store'})
    with tarfile.open(OUT / 'implementation-overlay.tar.gz', 'w:gz') as archive:
        for name in sources:
            archive.add(ROOT / name, arcname=name)
    profiles = {}
    with tarfile.open(OUT / 'release/profiles-and-c.tar.gz', 'w:gz') as archive:
        for directory in sorted((ROOT / 'build/release-workflow').iterdir()):
            if not directory.is_dir():
                continue
            selected = [directory / 'program.c', directory / 'merged.profdata']
            selected += sorted((directory / 'profiles').rglob('*.profraw'))
            for path in selected:
                if path.is_file():
                    name = str(path.relative_to(ROOT / 'build/release-workflow'))
                    archive.add(path, arcname=name)
                    profiles[name] = digest(path)
    manifest = {
        'baseline_commit': '5595ee6b99164897fb50e28772c4be755f2a9461',
        'overlay_instructions': 'Extract baseline/source.tar.gz into an empty directory, then implementation-overlay.tar.gz into the same directory. Install project dependencies before reproducing commands in REPORT.md.',
        'source_sha256': {name: digest(ROOT / name) for name in sources},
        'release_archive_sha256': profiles,
        'evidence_sha256': {str(p.relative_to(OUT)): digest(p)
                           for p in sorted(OUT.rglob('*'))
                           if p.is_file() and p.name != 'manifest.json'},
    }
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Packaged {len(sources)} source files and {len(profiles)} release inputs.')


if __name__ == '__main__':
    main()
