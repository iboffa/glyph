"""Evaluate the isolated explicit-root collector; not a production GC switch."""
import json, os, random, statistics, subprocess, time
from pathlib import Path
from glyph.backend import compile_c
ROOT=Path(__file__).resolve().parents[1]
def main():
    out=ROOT/'benchmarks/results/macos-arm64-2026-10-28-memory/precise';out.mkdir(parents=True,exist_ok=True)
    build=ROOT/'build/precise-experiment';build.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'benchmarks/precise_experiment.c').read_text().replace('#include "runtime.h"',(ROOT/'glyph/runtime.h').read_text()).replace('#include "precise_gc.h"',(ROOT/'benchmarks/precise_gc.h').read_text())
    results={'scope':'Single-thread explicit-root/layout microbenchmark; no language root lowering, concurrent publication, or moving objects. Both variants force collection after each 256 nodes. Not representative of default BDWGC scheduling.','runs':{}}
    for variant in ['precise','bdwgc']:
        c=build/(variant+'.c');c.write_text(('#define PRECISE 1\n' if variant=='precise' else '')+source)
        exe=build/variant
        started=time.perf_counter();command=compile_c(c,exe,cc_override='/usr/bin/clang');elapsed=time.perf_counter()-started
        results['runs'][variant]={'build_s':elapsed,'bytes':exe.stat().st_size,'command':command,'samples':[]}
    rng=random.Random(28)
    for trial in range(8):
        order=['precise','bdwgc'];rng.shuffle(order)
        for variant in order:
            p=subprocess.run([build/variant],text=True,capture_output=True,check=True)
            lines=p.stdout.splitlines();assert int(lines[0])==1000*128*129//2+73,p.stdout
            if trial:results['runs'][variant]['samples'].append(float(lines[1]))
    for d in results['runs'].values():d['median_s']=statistics.median(d['samples'])
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(out/'results.json')
if __name__=='__main__':main()
