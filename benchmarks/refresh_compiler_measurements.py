"""Refresh compiler measurements after a frontend-only fix.

First require byte-identical native output for every measured application. The
application timings remain valid only if all generated-C hashes match. Original
compiler observations are retained in the result before replacement.
"""
import hashlib,json,random,statistics,subprocess,sys,time
from pathlib import Path
from . import release_workflow
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'benchmarks/results/macos-arm64-2026-10-28-memory'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    path=OUT/'comparison/results.json';d=json.loads(path.read_text())
    native=ROOT/'build/memory-selfhost/glyphc';scratch=ROOT/'build/memory-comparison/final-native.c'
    matches={}
    for key,row in d['builds'].items():
        case,variant=key.split('/')
        if variant!='native':continue
        source=OUT/'comparison/sources'/(case+'.gly')
        subprocess.run([native,'emit-c',source,'-o',scratch,'--runtime-dir',ROOT/'glyph'],check=True)
        actual=sha(scratch);assert actual==row['c_sha256'],(key,actual,row['c_sha256'])
        matches[key]=actual
    d['final_native_codegen_matches']=matches
    if 'compiler_before_size_guard' not in d:d['compiler_before_size_guard']=d['compiler']
    baseline=ROOT/'build/memory-baseline';source=baseline/'selfhost/compiler.gly'
    executables={'baseline':baseline/'build/selfhost/glyphc','combined':native}
    result={k:{'bytes':exe.stat().st_size,'sha256':sha(exe),'observations':[]} for k,exe in executables.items()}
    rng=random.Random(2810)
    for trial in range(8):
        order=list(executables);rng.shuffle(order)
        for variant in order:
            target=scratch.with_name('final-'+variant+'.c')
            command=[str(executables[variant]),'emit-c',str(source),'-o',str(target),'--runtime-dir',str(ROOT/'glyph')]
            start=time.perf_counter();subprocess.run(command,capture_output=True,text=True,check=True);wall=time.perf_counter()-start
            if trial:result[variant]['observations'].append({'wall_s':wall,'generated_c_bytes':target.stat().st_size,'command':command})
    result['input_sha256']=sha(source);d['compiler']=result
    path.write_text(json.dumps(d,indent=2)+'\n')
    for frontend in ('reference','native'):
        original=OUT/'release'/(frontend+'-compiler')/'results.json'
        archive=original.with_name('results-before-size-guard.json')
        if original.exists() and not archive.exists():original.rename(archive)
        sys.argv=['release_workflow','--frontend',frontend,'--compiler-workload','--samples','7']
        release_workflow.main()
    print('Final compiler timings refreshed; all application C hashes unchanged.')
if __name__=='__main__':main()
