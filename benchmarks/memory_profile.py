"""Sample only the benchmark child process, retaining macOS profiler evidence."""
import argparse,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--workers',default='4');ap.add_argument('--count',type=int,default=4000000);a=ap.parse_args()
    out=ROOT/'benchmarks/results/macos-arm64-2026-10-28-memory/profile';out.mkdir(parents=True,exist_ok=True)
    command=[str(ROOT/'build/memory-comparison/parallel-baseline'),str(a.count)]
    p=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(os.environ,GLYPH_WORKERS=a.workers))
    sample=['/usr/bin/sample',str(p.pid),'1','-file',str(out/'baseline-parallel.txt')]
    q=subprocess.run(sample,capture_output=True,text=True,timeout=15)
    stdout,stderr=p.communicate(timeout=90)
    expected=5*128*a.count*(a.count-1)//2
    assert p.returncode==0 and int(stdout.splitlines()[0])==expected
    report={'command':command,'workers':a.workers,'sample_command':sample,'sample_returncode':q.returncode,'sample_stdout':q.stdout,'sample_stderr':q.stderr,'stdout':stdout,'stderr':stderr,'note':'Profiler run is excluded from timing comparisons; samples are statistical stacks, not exact attribution.'}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n');print(out/'results.json')
if __name__=='__main__':main()
