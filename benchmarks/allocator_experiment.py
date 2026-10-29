"""BDWGC global vs thread-local allocation caches, keeping one shared collector."""
import json,os,random,statistics,subprocess,time
from pathlib import Path
from glyph.backend import compile_c,compiler
from glyph.gc_support import collector_flags,VENDOR
ROOT=Path(__file__).resolve().parents[1]
def main():
    out=ROOT/'benchmarks/results/macos-arm64-2026-10-28-memory/allocator';out.mkdir(parents=True,exist_ok=True)
    build=ROOT/'build/allocator-experiment';build.mkdir(parents=True,exist_ok=True)
    source=ROOT/'benchmarks/results/macos-arm64-2026-10-28-memory/comparison/sources/parallel-baseline.c'
    report={'scope':'Same shared, nonmoving collector and registered worker stacks. THREAD_LOCAL_ALLOC changes allocation caches, not ownership or collection domains. Both programs are baseline generated C; compiler stack promotion disabled.', 'runs':{}}
    cc=compiler();env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(ROOT/'build/.glyph-cache'),ZIG_LOCAL_CACHE_DIR=str(ROOT/'build/.glyph-cache'))
    obj=build/'tla.o';cmd=cc+collector_flags(threaded=True)+['-DTHREAD_LOCAL_ALLOC','-c',str(VENDOR/'extra/gc.c'),'-o',str(obj)]
    p=subprocess.run(cmd,capture_output=True,text=True,env=env)
    report['collector_build']={'command':cmd,'returncode':p.returncode,'stderr':p.stderr}
    if p.returncode:
        (out/'results.json').write_text(json.dumps(report,indent=2));return
    for variant in ('global','thread_local'):
        exe=build/variant;command=compile_c(source,exe)
        if variant=='thread_local':
            command=[str(obj) if x.endswith('.o') and 'bdwgc-' in x else x for x in command]
            subprocess.run(command,capture_output=True,text=True,check=True,env=env)
        for workers in (1,2,4):report['runs'][f'{variant}/{workers}']={'samples':[],'command':command,'workers':workers,'bytes':exe.stat().st_size}
    rng=random.Random(28)
    for trial in range(8):
        keys=list(report['runs']);rng.shuffle(keys)
        for key in keys:
            variant,w=key.split('/');env=dict(os.environ,GLYPH_WORKERS=w)
            start=time.perf_counter();p=subprocess.run([build/variant,'100000'],env=env,text=True,capture_output=True,check=True);wall=time.perf_counter()-start
            lines=p.stdout.splitlines();assert int(lines[0])==5*128*100000*99999//2
            if trial:report['runs'][key]['samples'].append({'work_s':float(lines[-1]),'wall_s':wall})
    for d in report['runs'].values():d['median_work_s']=statistics.median(s['work_s'] for s in d['samples'])
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n');print(out/'results.json')
if __name__=='__main__':main()
