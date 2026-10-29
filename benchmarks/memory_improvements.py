"""Paired current/frozen-commit allocation benchmarks with independent ablations.

Timing runs do not enable counters, GC hooks or memory sampling. Instrumented
runs, exact OS peak RSS runs and compiler workloads are stored separately.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
import time

from glyph.backend import Emitter, compile_c
from glyph.checker import check
from glyph.syntax import parse
from .runtime import metadata
from .memory_cases import CASES

ROOT = Path(__file__).resolve().parents[1]

def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def cases():
    out = {}
    def wrap(work, iterations, expected):
        return (work + '''main>void
  setup := clock()
  n := argi(0)
  setup = clock() - setup
  start := clock()
  total := 0
  i := 0
  while i < n
    total += work(i)
    i += 1
  elapsed := clock() - start
  print(total)
  print(setup)
  print(elapsed)
''', [iterations], expected)
    out['temporary'] = wrap('work x:int>int\n  a := fill(64, x)\n  ret sum(a)\n', 30000, 64*30000*29999//2)
    out['closure'] = wrap('work x:int>int\n  f := fn(y:int)>int = x + y\n  ret f(3)\n', 200000, 200000*199999//2+3*200000)
    out['escaping'] = wrap('make x:int>[int] = fill(64, x)\nwork x:int>int\n  a := make(x)\n  b := a\n  a[0] += 1\n  ret sum(b)\n', 30000, 64*30000*29999//2+30000)
    out['fusion'] = wrap('work x:int>int = sum(fill(64, x))\n', 30000, 64*30000*29999//2)
    out['checks'] = wrap('work x:int>int\n  a := [x, x + 1, x + 2]\n  ret a[0] + a[1] + a[2] + (100 * 25)\n', 300000, 3*300000*299999//2+2503*300000)
    for name in ('numeric', 'cycles', 'text'):
        n = 3000 if name in {'numeric', 'cycles'} else 1000
        out[name] = wrap(CASES[name]['source'].split('main>void')[0], n, CASES[name]['expected'](n))
    out['retained_slices'] = ('''type View
  text:str
main>void
  setup := clock()
  n := argi(0)
  keep := fill(32, View(""))
  setup = clock() - setup
  start := clock()
  i := 0
  while i < n
    text := concat("prefix-", str_i64(i))
    keep[i % 32] = View(slice(text, 7, len(text)))
    i += 1
  total := 0
  for v:keep
    total += parse_i64(v.text)
  elapsed := clock() - start
  print(total)
  print(setup)
  print(elapsed)
''', [30000], sum(range(30000-32,30000)))
    out['reuse'] = ('''main>void
  setup := clock()
  n := argi(0)
  width := argi(1)
  a := fill(width, 0)
  setup = clock() - setup
  start := clock()
  i := 0
  total := 0
  while i < n
    a = fill(width, i)
    total += sum(a)
    i += 1
  elapsed := clock() - start
  print(total)
  print(setup)
  print(elapsed)
''', [10000,512], 512*10000*9999//2)
    out['startup'] = ('main>void\n  ret\n', [], None)
    parallel = '''work x:int>int
  a := fill(128, x)
  ret sum(a)
main>void
  setup := clock()
  a := range(argi(0))
  setup = clock() - setup
  start := clock()
  r := 0
  total := 0
  while r < 5
    b := par_map(a, work)
    total += sum(b)
    r += 1
  elapsed := clock() - start
  print(total)
  print(setup)
  print(elapsed)
'''
    out['parallel'] = (parallel, [100000], 5*128*100000*99999//2)
    # Explicit-domain workloads have comparable fill/reduction work. Arenas are
    # scoped per batch of 1000; owned storage is freed on each iteration.
    for domain in ('arena', 'owned'):
        work = ('work x:int>int\n  arena\n    a := arena_fill(64, x)\n    ret sum(a)\n' if domain == 'arena' else
                'work x:int>int\n  b := owned_fill(64, x)\n  total := 0\n  borrow a = b\n    total = sum(a)\n  free(b)\n  ret total\n')
        out[domain] = wrap(work, 30000, 64*30000*29999//2)
    return out


def instrument_baseline(source):
    runtime = (ROOT/'glyph/runtime.h').read_text()
    definitions = runtime[runtime.index('#ifdef GLYPH_ALLOC_STATS'):runtime.index('static int g_argc;')]
    source = source.replace('static int g_argc;', definitions+'static int g_argc;', 1)
    source = source.replace('    GC_INIT();', '''    GC_INIT();
#ifdef GLYPH_ALLOC_STATS
    atexit(g_stats_report);
#endif
#ifdef GLYPH_GC_TIMING
    GC_set_on_collection_event(g_gc_event);
    atexit(g_gc_timing_report);
#endif''',1)
    source = source.replace('    size_t bytes = (n ? (size_t)n : 1) * size;', '    size_t bytes = (n ? (size_t)n : 1) * size;\n    G_ALLOC_RECORD(0, bytes);',1)
    return source


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, required=True, help='git archive extraction at starting commit')
    ap.add_argument('--native', type=Path, default=ROOT/'build/memory-selfhost/glyphc')
    ap.add_argument('--output', type=Path, default=ROOT/'benchmarks/results/macos-arm64-2026-10-28-memory/comparison')
    ap.add_argument('--samples', type=int, default=7)
    opts=ap.parse_args(); out=opts.output.resolve();out.mkdir(parents=True,exist_ok=True)
    build=ROOT/'build/memory-comparison';build.mkdir(parents=True,exist_ok=True)
    frozen=out/'sources';frozen.mkdir(exist_ok=True)
    report={'metadata':metadata(),'samples':opts.samples,'warmups':1,'seed':2810,'builds':{},'runs':{},'compiler':{},
            'method':'Randomized paired uninstrumented process runs; internal allocation-inclusive workload and setup clocks. Separate counters/GC event hooks and OS time peak-RSS runs. Explicit-domain programs are source variants, not automatic transformations. GC timings are collection events/stop-world intervals, not workload latency.',
            'limitations':['No thermal/affinity controls','RSS and final collector capacity include runtime/startup','Heap minus free is occupied capacity, not exact reachable bytes','Collector thread CPU excludes other threads and parallel marking','GC samples capped at 4096; counts expose truncation']}
    variants={'baseline':None,'unoptimized':set(),'stack':{'stack'},'reuse':{'reuse'},'fusion':{'fusion'},'init':{'init'},'checks':{'bounds','overflow'},'combined':None,'native':None}
    commands={}; instrumented={}; expected={}
    for name,(source,arguments,answer) in cases().items():
        path=frozen/(name+'.gly');path.write_text(source)
        for variant,features in variants.items():
            if name in {'arena','owned'} and variant not in {'combined','native'}:
                continue
            key=name+'/'+variant
            cpath=frozen/(name+'-'+variant+'.c')
            started=time.perf_counter()
            if variant=='baseline':
                script='from glyph.modules import load_program; from glyph.checker import check; from glyph.backend import Emitter; from pathlib import Path; import sys; Path(sys.argv[2]).write_text(Emitter().emit(check(load_program(Path(sys.argv[1]))), sys.argv[1]))'
                subprocess.run([sys.executable,'-c',script,str(path),str(cpath)],cwd=opts.baseline,check=True)
                cpath.write_text(instrument_baseline(cpath.read_text()))
            elif variant=='native':
                subprocess.run([opts.native.resolve(),'emit-c',path,'-o',cpath,'--runtime-dir',ROOT/'glyph'],check=True)
            else:
                script='from glyph.modules import load_program; from glyph.checker import check; from glyph.backend import Emitter; from pathlib import Path; import json,sys; options=json.loads(sys.argv[3]); Path(sys.argv[2]).write_text(Emitter(**options).emit(check(load_program(Path(sys.argv[1]))), sys.argv[1]))'
                options={'optimize':variant!='unoptimized','optimizations':sorted(features) if features is not None else None}
                subprocess.run([sys.executable,'-c',script,str(path),str(cpath),json.dumps(options)],cwd=ROOT,check=True)
            frontend_s=time.perf_counter()-started
            exe=build/(name+'-'+variant)
            zero=variant in {'unoptimized','stack','reuse','fusion','checks'}
            started=time.perf_counter();flags=compile_c(cpath,exe,zero_init=zero);build_s=time.perf_counter()-started
            report['builds'][key]={'frontend_s':frontend_s,'backend_s':build_s,'bytes':exe.stat().st_size,'command':flags,'source_sha256':digest(path),'c_sha256':digest(cpath)}
            measured=exe.with_name(exe.name+'-stats')
            compile_c(cpath,measured,stats=True,gc_timing=True,zero_init=zero)
            for workers in ((1,2,4) if name=='parallel' else (1,)):
                runkey=key+'/'+str(workers)
                commands[runkey]=([str(exe),*map(str,arguments)],workers)
                instrumented[runkey]=([str(measured),*map(str,arguments)],workers)
                expected[runkey]=answer
        print('Built',name,flush=True)
    def run(key, command, workers, memory=False):
        env=dict(os.environ,GLYPH_WORKERS=str(workers),GLYPH_GC_STRESS='0')
        cmd=(['/usr/bin/time','-l'] if memory and sys.platform=='darwin' else [])+command
        started=time.perf_counter();p=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=120,check=True);wall=time.perf_counter()-started
        lines=p.stdout.splitlines()
        if expected[key] is not None and (not lines or int(lines[0]) != expected[key]):
            raise AssertionError((key,p.stdout,expected[key]))
        data={'wall_s':wall,'setup_s':float(lines[1]) if len(lines)>1 else None,'work_s':float(lines[2]) if len(lines)>2 else None,'stdout':p.stdout}
        for line in p.stderr.splitlines():
            if line.startswith('GLYPH_MEMORY '): data['allocation']=json.loads(line[13:])
            if line.startswith('GLYPH_GC '): data['gc']=json.loads(line[9:])
            if 'maximum resident set size' in line: data['peak_rss_bytes']=int(line.split()[0])
        return data
    for key,(cmd,workers) in commands.items():
        run(key,cmd,workers)
        report['runs'][key]={'command':cmd,'workers':workers,'observations':[]}
    rng=random.Random(2810)
    for trial in range(opts.samples):
        order=list(commands);rng.shuffle(order)
        for key in order:
            cmd,workers=commands[key];report['runs'][key]['observations'].append(run(key,cmd,workers))
        print('Verified trial',trial+1,flush=True)
    for key,(cmd,workers) in commands.items():
        data=report['runs'][key]
        data['memory_control']=run(key,cmd,workers,True)
        icmd,_=instrumented[key];data['instrumented']=run(key,icmd,workers,True)
        data['median_wall_s']=statistics.median(x['wall_s'] for x in data['observations'])
        times=[x['work_s'] for x in data['observations'] if x['work_s'] is not None]
        if times: data.update(median_work_s=statistics.median(times),min_work_s=min(times),max_work_s=max(times))
    # Same frozen compiler input, same mode, both native compiler executables.
    compiler_input=opts.baseline.resolve()/'selfhost/compiler.gly'
    for variant,exe in [('baseline',opts.baseline.resolve()/'build/selfhost/glyphc'),('combined',opts.native.resolve())]:
        report['compiler'][variant]={'bytes':exe.stat().st_size,'sha256':digest(exe),'observations':[]}
    order=['baseline','combined']
    compilers={'baseline':opts.baseline.resolve()/'build/selfhost/glyphc','combined':opts.native.resolve()}
    for trial in range(opts.samples+1):
        rng.shuffle(order)
        for variant in order:
            target=build/('compiler-'+variant+'.c')
            cmd=[str(compilers[variant]),'emit-c',str(compiler_input),'-o',str(target),'--runtime-dir',str(ROOT/'glyph')]
            started=time.perf_counter();p=subprocess.run(cmd,capture_output=True,text=True,check=True);elapsed=time.perf_counter()-started
            if trial:report['compiler'][variant]['observations'].append({'wall_s':elapsed,'generated_c_bytes':target.stat().st_size})
    report['compiler']['input_sha256']=digest(compiler_input)
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(out/'results.json')

if __name__=='__main__': main()
