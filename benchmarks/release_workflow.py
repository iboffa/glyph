"""Reproducible Clang instrumentation PGO, LTO and CPU-target evaluation.

Examples:
 python -m benchmarks.release_workflow --frontend reference
 python -m benchmarks.release_workflow --frontend native --compiler-workload
All invocations, profile hashes, training/evaluation inputs and raw results are
retained. An unchanged C path is used for instrumentation and profile use.
"""
import argparse, hashlib, json, os, random, statistics, subprocess, sys, time
from pathlib import Path
from glyph.backend import Emitter, compile_c
from glyph.checker import check
from glyph.modules import load_program
ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--frontend',choices=['reference','native'],default='reference')
    ap.add_argument('--native',type=Path,default=ROOT/'build/memory-selfhost/glyphc')
    ap.add_argument('--compiler-workload',action='store_true')
    ap.add_argument('--samples',type=int,default=7)
    ap.add_argument('--output',type=Path,default=ROOT/'benchmarks/results/macos-arm64-2026-10-28-memory/release')
    opts=ap.parse_args();tag=opts.frontend+('-compiler' if opts.compiler_workload else '-array')
    out=opts.output.resolve()/tag;out.mkdir(parents=True,exist_ok=True)
    build=ROOT/'build/release-workflow'/tag;build.mkdir(parents=True,exist_ok=True)
    cpath=build/'program.c';source=ROOT/('selfhost/compiler.gly' if opts.compiler_workload else 'benchmarks/programs/array.gly')
    if opts.frontend=='native':subprocess.run([opts.native.resolve(),'emit-c',source,'-o',cpath,'--runtime-dir',ROOT/'glyph'],check=True)
    else:cpath.write_text(Emitter().emit(check(load_program(source)),source))
    if opts.compiler_workload:
        training=[['check',str(ROOT/'examples'/p)] for p in ('sum.gly','records.gly','calculator.gly')]
        heldout=['emit-c',str(ROOT/'build/memory-baseline/selfhost/compiler.gly'),'-o',str(build/'heldout.c'),'--runtime-dir',str(ROOT/'glyph')]
    else:
        training=[['10000','10','17'],['50000','15','73'],['1000','3','11']]
        heldout=['200000','100','37']
    def expected_array(args):
        n,repeats,seed=map(int,args)
        values=[(i*17+seed)%1000 for i in range(n)]
        checksum=0
        for r in range(repeats):
            values[r%n]=(values[r%n]+r)%1000
            checksum+=sum(values)
        return str(checksum)
    raw=build/'profiles';raw.mkdir(exist_ok=True)
    # A unique directory per invocation prevents accidental merging of stale runs.
    run_raw=raw/str(time.time_ns());run_raw.mkdir()
    prof=build/'merged.profdata';instrument=build/'instrumented'
    report={'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'c_sha256':hashlib.sha256(cpath.read_bytes()).hexdigest(),
            'frontend':opts.frontend,'cc':'/usr/bin/clang','cc_version':subprocess.check_output(['/usr/bin/clang','--version'],text=True),'profdata_version':subprocess.check_output(['xcrun','llvm-profdata','merge','--version'],text=True),'training':training,'heldout':heldout,'runs':{},'training_runs':[]}
    started=time.perf_counter();report['instrument_command']=compile_c(cpath,instrument,cc_override='/usr/bin/clang',profile_generate=run_raw/'%p.profraw');report['instrument_build_s']=time.perf_counter()-started
    for args in training:
        started=time.perf_counter();p=subprocess.run([instrument,*args],text=True,capture_output=True,check=True)
        if not opts.compiler_workload:assert p.stdout.splitlines()[0]==expected_array(args)
        report['training_runs'].append({'args':args,'wall_s':time.perf_counter()-started,'stdout':p.stdout})
    merge=['xcrun','llvm-profdata','merge','-o',str(prof),*map(str,sorted(run_raw.glob('*.profraw')))];subprocess.run(merge,check=True)
    report['merge_command']=merge;report['profile_sha256']=hashlib.sha256(prof.read_bytes()).hexdigest()
    variants={'portable':{},'thin_lto':{'lto':'thin'},'full_lto':{'lto':'full'},'native_cpu':{'cpu':'native'},'pgo':{'profile_use':prof},'pgo_thin_lto':{'profile_use':prof,'lto':'thin'}}
    for variant,flags in variants.items():
        exe=build/variant;times=[]
        for _ in range(2):
            started=time.perf_counter();command=compile_c(cpath,exe,cc_override='/usr/bin/clang',**flags);times.append(time.perf_counter()-started)
        report['runs'][variant]={'build_s':times,'bytes':exe.stat().st_size,'command':command,'samples':[]}
    rng=random.Random(2810);expected='' if opts.compiler_workload else expected_array(heldout)
    for trial in range(opts.samples+1):
        order=list(variants);rng.shuffle(order)
        for variant in order:
            started=time.perf_counter();p=subprocess.run([build/variant,*heldout],text=True,capture_output=True,check=True);elapsed=time.perf_counter()-started
            lines=p.stdout.splitlines();answer=lines[0] if lines else ''
            if expected is None:expected=answer
            assert answer==expected,(variant,p.stdout,expected)
            sample={'wall_s':elapsed,'stdout':p.stdout,'kernel_s':float(lines[-1]) if len(lines)>1 else None}
            if opts.compiler_workload:sample['output_sha256']=hashlib.sha256((build/'heldout.c').read_bytes()).hexdigest()
            if trial:report['runs'][variant]['samples'].append(sample)
    for d in report['runs'].values():
        d['median_wall_s']=statistics.median(x['wall_s'] for x in d['samples'])
        if not opts.compiler_workload:d['median_kernel_s']=statistics.median(x['kernel_s'] for x in d['samples'])
    if opts.compiler_workload:assert len({s['output_sha256'] for d in report['runs'].values() for s in d['samples']})==1
    report['expected_stdout_first_line']=expected
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n');print(out/'results.json')
if __name__=='__main__':main()
