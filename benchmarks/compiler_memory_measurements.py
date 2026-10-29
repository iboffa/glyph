"""Separate OS peak-RSS and allocation/GC-event runs of both native compilers."""
import json,subprocess
from pathlib import Path
from glyph.backend import compile_c
from .memory_improvements import instrument_baseline
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'benchmarks/results/macos-arm64-2026-10-28-memory'
def main():
    path=OUT/'comparison/results.json';data=json.loads(path.read_text())
    build=ROOT/'build/compiler-memory';build.mkdir(parents=True,exist_ok=True)
    baseline=ROOT/'build/memory-baseline';source=baseline/'selfhost/compiler.gly'
    for variant,exe in [('baseline',baseline/'build/selfhost/glyphc'),('combined',ROOT/'build/memory-selfhost/glyphc')]:
        text=Path(str(exe)+'.c').read_text()
        if variant=='baseline':text=instrument_baseline(text)
        c=build/(variant+'.c');c.write_text(text);stats=build/(variant+'-stats')
        command=compile_c(c,stats,cc_override='/usr/bin/clang',stats=True,gc_timing=True)
        records={}
        outputs=[]
        for name,binary in [('memory_control',exe),('instrumented',stats)]:
            target=build/(variant+'-'+name+'.c')
            cmd=['/usr/bin/time','-l',str(binary),'emit-c',str(source),'-o',str(target),'--runtime-dir',str(ROOT/'glyph')]
            p=subprocess.run(cmd,capture_output=True,text=True,check=True,timeout=60)
            record={'command':cmd}
            for line in p.stderr.splitlines():
                if 'maximum resident set size' in line:record['peak_rss_bytes']=int(line.split()[0])
                if line.startswith('GLYPH_MEMORY '):record['allocation']=json.loads(line[13:])
                if line.startswith('GLYPH_GC '):record['gc']=json.loads(line[9:])
            records[name]=record;outputs.append(target.read_bytes())
        assert outputs[0]==outputs[1],variant
        data['compiler'][variant].update(records)
        data['compiler'][variant]['instrument_command']=command
    path.write_text(json.dumps(data,indent=2)+'\n');print('Compiler memory controls verified.')
if __name__=='__main__':main()
