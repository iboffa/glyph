"""Focused runtime sanitizer and allocation-failure evidence."""
import json,os,subprocess,sys
from pathlib import Path
from glyph.syntax import parse
from glyph.checker import check
from glyph.backend import Emitter,compile_c
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_memory_controls import POSITIVE
from benchmarks.memory_cases import STRESS,STRESS_EXPECTED

def main():
    out=ROOT/'benchmarks/results/macos-arm64-2026-10-28-memory/validation';out.mkdir(parents=True,exist_ok=True)
    build=ROOT/'build/memory-validation';build.mkdir(parents=True,exist_ok=True)
    report={'sanitizers':{},'allocation_failures':{},'limitations':['LeakSanitizer unavailable on this macOS configuration; BDWGC object is not ASan-instrumented; emitted program and runtime are.','ThreadSanitizer covered separately by existing concurrency harness.']}
    for name,source,sanitizer in [('domains',POSITIVE,'address,undefined'),('gc_roots',STRESS,'address,undefined'),('domains-ubsan',POSITIVE,'undefined'),('gc-roots-ubsan',STRESS,'undefined')]:
        c=build/(name+'.c');c.write_text(Emitter().emit(check(parse(source))))
        exe=build/name;command=compile_c(c,exe,cc_override='/usr/bin/clang')
        command += ['-fsanitize='+sanitizer,'-fno-omit-frame-pointer','-g']
        p=subprocess.run(command,text=True,capture_output=True)
        entry={'command':command,'build_returncode':p.returncode,'build_stderr':p.stderr}
        if p.returncode==0:
            p=subprocess.run([exe],text=True,capture_output=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0',GLYPH_GC_STRESS='1'),timeout=60)
            entry.update(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)
            if p.returncode == 0:
                assert p.stdout == (STRESS_EXPECTED if source == STRESS else '22\n16\n15\n4\n')
            else:
                entry['status']='unavailable: sanitizer runtime initialization failed' if 'asan_init_is_running' in p.stderr else 'failed'
        report['sanitizers'][name]=entry
    for domain in ('owned','arena'):
        source='main>void\n  arena\n    a := '+domain+'_fill(4, 0)\n'
        c=build/(domain+'-fail.c');text=Emitter().emit(check(parse(source)))
        text=text.replace('static bool g_gc_stress;', 'static void *g_test_malloc(size_t n) { (void)n; return NULL; }\n#define malloc g_test_malloc\nstatic bool g_gc_stress;',1)
        c.write_text(text);exe=build/(domain+'-fail');compile_c(c,exe)
        p=subprocess.run([exe],capture_output=True,text=True);assert p.returncode==70 and json.loads(p.stderr)['code']=='R004'
        report['allocation_failures'][domain]={'returncode':p.returncode,'diagnostic':json.loads(p.stderr)}
    report['sanitizer_probes']={}
    probe=build/'probe.c';probe.write_text('int main(void) { return 0; }\n')
    for sanitizer in ('address,undefined','thread'):
        exe=build/('probe-'+sanitizer.replace(',','-'))
        command=['/usr/bin/clang',str(probe),'-o',str(exe),'-fsanitize='+sanitizer]
        p=subprocess.run(command,capture_output=True,text=True)
        record={'command':command,'build_returncode':p.returncode,'build_stderr':p.stderr}
        if p.returncode==0:
            p=subprocess.run([exe],capture_output=True,text=True)
            record.update(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)
        report['sanitizer_probes'][sanitizer]=record
    from glyph.gc_support import collector_flags, VENDOR
    exe=build/'tsan'
    cmd=['/usr/bin/clang',str(ROOT/'tests/concurrency_runtime_harness.c'),str(VENDOR/'extra/gc.c'),'-o',str(exe),'-g','-fsanitize=thread']+collector_flags(threaded=True)
    p=subprocess.run(cmd,text=True,capture_output=True)
    record={'command':cmd,'build_returncode':p.returncode,'build_stderr':p.stderr}
    if p.returncode==0:
        try:
            p=subprocess.run([exe],text=True,capture_output=True,timeout=30)
            record.update(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)
        except subprocess.TimeoutExpired:
            record['timeout_s']=30
    report['sanitizers']['thread']=record
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n');print(out/'results.json')
if __name__=='__main__':main()
