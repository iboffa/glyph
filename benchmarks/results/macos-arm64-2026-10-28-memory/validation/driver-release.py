import json, os, subprocess, sys
from pathlib import Path
root=Path.cwd();build=root/'build/memory-cli';build.mkdir(exist_ok=True)
records=[]
def run(cmd):
 p=subprocess.run(list(map(str,cmd)),capture_output=True,text=True)
 records.append({'command':list(map(str,cmd)),'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
 assert p.returncode==0,(cmd,p.stderr)
 return p
for name,driver in [('reference',[sys.executable,'-m','glyph']),('native',[root/'build/memory-selfhost/glyphc'])]:
 exe=build/name;raw=build/(name+'.profraw');prof=build/(name+'.profdata')
 common=[*driver,'build',root/'examples/memory.gly','-o',exe,'--cc','/usr/bin/clang']
 if name=='native': common+=['--runtime-dir',root/'glyph']
 run([*common,'--profile-generate',raw])
 assert run([exe]).stdout=='20\n16\n15\n'
 run(['xcrun','llvm-profdata','merge','-o',prof,raw])
 run([*common,'--profile-use',prof,'--lto','thin','--cpu','native'])
 assert run([exe]).stdout=='20\n16\n15\n'
(root/'benchmarks/results/macos-arm64-2026-10-28-memory/validation/driver-release.json').write_text(json.dumps(records,indent=2)+'\n')
print('Both standalone drivers: profile generation/use, thin LTO, native CPU and memory example passed.')
