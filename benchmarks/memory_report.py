"""Summarize retained observations without estimating missing metrics."""
import json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'benchmarks/results/macos-arm64-2026-10-28-memory'
def read(path):return json.loads((OUT/path).read_text())
def med(values):return statistics.median(values)
def ms(x):return f'{1000*x:.3f}'
def pct(a,b):return f'{100*(b/a-1):+.1f}%'
def main():
    d=read('comparison/results.json');meta=read('baseline/metadata.json')
    lines=['# Memory and compiler improvements — 2026-10-28','',
        'Starting commit: `5595ee6b99164897fb50e28772c4be755f2a9461`. The pre-existing `.DS_Store` change and subsequently appearing `examples/.DS_Store` were preserved.', '',
        f"Host: {meta['cpu_model']}, {meta['physical_cores']} physical/{meta['logical_cores']} logical cores, {meta['ram_bytes']/2**30:.0f} GiB RAM, `{meta['os']}`. Python {meta['python'].split()[0]}, Zig {meta['ziglang']}. Exact compiler versions, flags and environment are in [baseline metadata](baseline/metadata.json).",'',
        '## What shipped','',
        'Both frontends implement checked `@noalloc`, primitive scoped arenas, affine local owned buffers with move/free and unique scoped borrowing, bounded stack arrays/scalar closure environments, direct local-closure calls, alias-checked fill-buffer reuse, immediate construction/reduction fusion, narrow check proofs and removal of redundant pointer-free initialization. PGO/LTO/native-target flags preserve checked arithmetic and floating-point flags. Allocation/GC-event instrumentation is opt-in. BDWGC remains the default nonmoving collector. See [language contracts](../../../docs/MEMORY_CONTROLS.md) and [release workflow](../../../docs/RELEASE_OPTIMIZATION.md).','',
        '## Correctness and reproducibility','',
        '- Baseline: 123 tests, six skips. Final reference run: 132 tests, three skips (live GUI and two Linux `/dev/full` cases), no failures. The native differential corpus reports its exact check/emission counts in [the native log](native-tests.log); the memory-control tests additionally exercise both compilers at O0/O1/O2/O3 and under GC stress.',
        '- Three-stage bootstrap fixed point verified; stage 2 and stage 3 C match byte for byte. [Bootstrap evidence](bootstrap/verification.json).',
        '- Negative tests cover aliases, closures, generic contracts, unknown callbacks, recursion, region/borrow escape, unsupported reference layouts, use after move/free, double-free, outer-owner consumption and unreachable region blocks. Disjoint lexical names cannot be conflated by optimization proofs.',
        '- UBSan passes explicit storage and GC-root/slice/cycle/pointer workloads. ASan aborts during sanitizer initialization and TSan segfaults even for an empty C `main`; their checks are unavailable on this host, not claimed as passes. [Exact commands and minimal probes](validation/results.json). Explicit malloc-failure injection produces R004 for both domains.',
        '- Both standalone drivers also build/run the memory example using profile generation/use, thin LTO and native CPU flags. [Driver checks](validation/driver-release.json).',
        '- The final matrix uses file-based loading and subprocess frontend invocation for both baseline and current reference variants. Preliminary observations with mismatched file-location metadata are retained in `preliminary-results.tar.gz` and are superseded. They are not used in the tables below.','',
        '## Paired workload results','',
        'Seven uninstrumented process trials after one warmup per case; deterministic randomized order. Internal work intervals include the allocations being studied. Setup is separately clocked, and whole-process wall time includes startup/output/cleanup. No correctness suites or other benchmark suites ran concurrently with the final timing matrix. Values below are medians; brackets contain observed minima and maxima. They are not confidence intervals.','',
        '| Workload | Baseline ms [range] | Combined ms [range] | Change | GC allocation requests, baseline → combined |',
        '|---|---:|---:|---:|---:|']
    for case in ['temporary','closure','escaping','fusion','checks','numeric','cycles','text','retained_slices','reuse']:
        a=d['runs'][case+'/baseline/1'];b=d['runs'][case+'/combined/1']
        def value(r):return f"{ms(r['median_work_s'])} [{ms(r['min_work_s'])}, {ms(r['max_work_s'])}]"
        ca=a['instrumented']['allocation']['gc_count'];cb=b['instrumented']['allocation']['gc_count']
        lines.append(f"| {case} | {value(a)} | {value(b)} | {pct(a['median_work_s'],b['median_work_s'])} | {ca:,} → {cb:,} |")
    lines += ['', 'Allocation elimination helps the eligible temporary/closure/fusion/reuse kernels. Escaping arrays, cyclic graphs, string allocation and retained slices remain on the managed path; small changes there should not be interpreted as universal improvements. Check elimination alone provides little benefit in these kernels because LLVM already removes many checks.','',
        '### Independent transformations','',
        'Ablations use the current runtime with frontend transformations disabled and zeroing restored as their control. This separates each transformation from baseline-to-current runtime/code-generation differences.','',
        '| Workload / feature | Current unoptimized ms | Feature alone ms | Combined ms |', '|---|---:|---:|---:|']
    for case,feature in [('temporary','stack'),('closure','stack'),('reuse','reuse'),('fusion','fusion'),('numeric','init'),('checks','checks')]:
        vals=[d['runs'][case+'/'+v+'/1']['median_work_s'] for v in ['unoptimized',feature,'combined']]
        lines.append(f'| {case} / {feature} | '+' | '.join(ms(x) for x in vals)+' |')
    lines += ['', 'Stack/closure ablation includes direct local-closure targeting. The init ablation restores zeroing in the control, including runtime clone/range helpers. The full raw matrix includes all features on every ordinary workload, so unsuccessful and potentially regressing cases remain visible.','',
        '### Explicit domains','', '| Variant, same 30,000 × 64-element fill/reduction workload | Work ms | GC / arena / owned requests | Peak RSS MiB |','|---|---:|---:|---:|']
    for case,var in [('temporary','baseline'),('temporary','combined'),('arena','combined'),('owned','combined')]:
        r=d['runs'][case+'/'+var+'/1'];a=r['instrumented']['allocation']
        lines.append(f"| {case}/{var} | {ms(r['median_work_s'])} | {a['gc_count']:,} / {a['arena_count']:,} / {a['owned_count']:,} | {r['memory_control']['peak_rss_bytes']/2**20:.2f} |")
    lines += ['', 'The arena case creates/releases an arena per function call; chunk setup dominates this small allocation. It demonstrates a regression, not a recommended arena batching strategy. Owned malloc/free is explicit and bounded by scope, but stack promotion is faster for this eligible workload. These source variants have different lifetime-management operations; they are not automatic transformations of the baseline program.','',
        '### Parallel allocation','', '| Workers | Baseline ms | Combined ms | Million callbacks/s, baseline → combined | Baseline requests | Combined requests |', '|---:|---:|---:|---:|---:|---:|']
    for w in (1,2,4):
        a=d['runs'][f'parallel/baseline/{w}'];b=d['runs'][f'parallel/combined/{w}']
        lines.append(f"| {w} | {ms(a['median_work_s'])} | {ms(b['median_work_s'])} | {0.5/a['median_work_s']:.2f} → {0.5/b['median_work_s']:.2f} | {a['instrumented']['allocation']['gc_count']:,} | {b['instrumented']['allocation']['gc_count']:,} |")
    lines += ['', 'Each trial maps 100,000 elements five times, with 128-element temporary callback arrays. One-worker mode uses the same threaded binary/collector. Output-array allocations remain. [A separate statistical profile](profile/baseline-parallel.txt) samples `GC_malloc_kind_global` and `GC_lock` in the baseline; it is excluded from timing results.','',
        '## Memory and GC observations','',
        'The raw matrix retains an uninstrumented `/usr/bin/time -l` peak-RSS control and a separate counter/GC-hook run for every variant. Counter overhead is therefore observable rather than mixed into the primary timings. Each control is one process; it is not a repeated estimate of instrumentation overhead.','',
        '| Case | Peak RSS MiB, baseline → combined | Final GC capacity KiB, baseline → combined | Requested GC bytes, baseline → combined |','|---|---:|---:|---:|']
    for case in ['temporary','closure','numeric','reuse','retained_slices','cycles']:
        a=d['runs'][case+'/baseline/1'];b=d['runs'][case+'/combined/1'];aa=a['instrumented']['allocation'];ba=b['instrumented']['allocation']
        lines.append(f"| {case} | {a['memory_control']['peak_rss_bytes']/2**20:.2f} → {b['memory_control']['peak_rss_bytes']/2**20:.2f} | {aa['heap_bytes']/1024:.1f} → {ba['heap_bytes']/1024:.1f} | {aa['gc_bytes']:,} → {ba['gc_bytes']:,} |")
    lines += ['', 'Final capacity minus free bytes is occupied collector capacity, not precise reachable/retained bytes. Arena request bytes exclude chunk overhead; owned/arena capacity is reflected only in process RSS. There is no claim of exact live-byte accounting for the conservative collector.','',
        '| Instrumented case | Collection events | Collector-thread CPU ms | Stop-world p50 / p95 / max ms |','|---|---:|---:|---:|']
    for key in ['numeric/baseline/1','numeric/combined/1','parallel/baseline/4','parallel/combined/4','retained_slices/baseline/1']:
        g=d['runs'][key]['instrumented']['gc'];ps=sorted(g['stop_world_s'])
        desc='unobserved' if not ps else f'{ms(med(ps))} / {ms(ps[int(.95*(len(ps)-1))])} / {ms(max(ps))}'
        lines.append(f"| {key} | {g['collection_count']} | {ms(g['collector_thread_cpu_s'])} | {desc} |")
    lines += ['', 'These are collector event intervals, not batch latency. The sequential collector does not emit the stop/start-world events used here, so its pause samples are unavailable even when collection events are counted. Stop-world samples exclude suspension/resumption. Hooks are installed after GC initialization; startup collections are not timed. Samples cap at 4096; total counts expose truncation. Collector-thread CPU excludes other threads.','',
        '## Startup and compilation','']
    a=d['runs']['startup/baseline/1'];b=d['runs']['startup/combined/1']
    lines.append(f"Empty-process wall medians: {ms(a['median_wall_s'])} ms baseline, {ms(b['median_wall_s'])} ms combined ({pct(a['median_wall_s'],b['median_wall_s'])}). This is process startup, not kernel time.")
    lines += ['', '| Self-hosted compiler, same frozen compiler input | Median emit-C wall ms [range] | Executable bytes | Peak RSS MiB | GC requests / requested MiB |', '|---|---:|---:|---:|---:|---:|']
    for name in ('baseline','combined'):
        r=d['compiler'][name];times=[x['wall_s'] for x in r['observations']]
        alloc=r['instrumented']['allocation']
        lines.append(f"| {name} | {ms(med(times))} [{ms(min(times))}, {ms(max(times))}] | {r['bytes']:,} | {r['memory_control']['peak_rss_bytes']/2**20:.2f} | {alloc['gc_count']:,} / {alloc['gc_bytes']/2**20:.2f} |")
    lines += ['', 'The real compiler workload includes startup, module loading, checking, analysis and C emission. Additional analysis may regress this workload. The build table in the raw matrix records frontend process time, C backend time, executable sizes, commands and hashes for every case. Those build timings have one sample per case and uncontrolled warm caches; release comparisons below include two build samples per variant.','',
        '## PGO, LTO and CPU targeting','',
        'Training/evaluation inputs and profiles are separate. Both frontends are tested; compiler evaluation emits the same frozen source and verifies byte-identical outputs across release variants. Application C is profiled/LTO-optimized; the separately cached BDWGC object is not. Portable builds remain available.','',
        '| Native-emitted compiler variant | Held-out wall ms | Build seconds (two samples) | Executable bytes |','|---|---:|---:|---:|']
    rel=read('release/native-compiler/results.json')
    for name,r in rel['runs'].items():
        lines.append(f"| {name} | {ms(r['median_wall_s'])} | {r['build_s'][0]:.3f}, {r['build_s'][1]:.3f} | {r['bytes']:,} |")
    lines += ['', 'See [native compiler release results](release/native-compiler/results.json), [reference compiler results](release/reference-compiler/results.json), and the [reference](release/reference-array/results.json)/[native](release/native-array/results.json) array evaluations. PGO/LTO can help the compiler while providing little benefit or a small regression on the reduction kernel. No global release speedup is claimed.','',
        '## Collector experiments and decisions','',
        '| Shared BDWGC allocator | 1 worker ms | 2 workers ms | 4 workers ms |','|---|---:|---:|---:|']
    alloc=read('allocator/results.json')
    for name in ('global','thread_local'):
        lines.append('| '+name+' | '+' | '.join(ms(alloc['runs'][f'{name}/{w}']['median_work_s']) for w in (1,2,4))+' |')
    precise=read('precise/results.json')
    lines += ['', 'Thread-local allocation caches retain one shared collector and registered stacks, so this experiment does not weaken publication or pointer guarantees. They regressed multithreaded allocation in this workload and are not enabled. [Raw experiment](allocator/results.json).','',
        f"The isolated explicit-root/layout collector took {ms(precise['runs']['precise']['median_s'])} ms versus {ms(precise['runs']['bdwgc']['median_s'])} ms for the forced-collection cycle microbenchmark. It is nonmoving and tests an interior root, cyclic edges and complete reclamation. Both variants collect after each 256 nodes. This tiny explicit-root graph is favorable to the prototype and is not an application/backend comparison. [Source](../../../benchmarks/precise_gc.h) and [raw samples](precise/results.json).",'',
        'Not implemented as language backends: precise collection, worker-local collection, or moving/generational collection. The prototype has no compiler-emitted root stack, runtime/service root ABI, published-value protocol, safepoints, write barriers or pinning policy. Integrating any replacement without these would be unsound for strings, channels, escaping results and stable/interior pointers. These are deferred architectural work, not simultaneously shipped strategies.','',
        '## Remaining limits','',
        '- Explicit storage supports primitive elements and local owners only. Cross-function ownership transfer, reference-bearing layouts and worker use are rejected. No hidden managed references are allowed in malloc storage.',
        '- Analysis is conservative, with a small audited use grammar. General interprocedural escape precision, dynamic induction-range proofs and arbitrary callback fusion are not implemented. Native reports are narrower than reference reports.',
        '- No Windows/Linux run, GUI interaction run, functioning ASan/TSan run, precise live-byte accounting, power/affinity control or statistical confidence interval is claimed.',
        '- Input choices are bounded kernels and one compiler workload, not a representative application population. Read raw ranges and regressions before generalizing.','',
        '## Reproduce','',
        '```sh',
        'mkdir -p build/memory-baseline',
        'tar -xf benchmarks/results/macos-arm64-2026-10-28-memory/baseline/source.tar.gz -C build/memory-baseline',
        '# Bootstrap the frozen compiler from its own working directory:',
        '(cd build/memory-baseline && DEVELOPER_DIR=/Library/Developer/CommandLineTools ../../.venv/bin/python selfhost/bootstrap.py)',
        'DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python selfhost/bootstrap.py --output-dir build/memory-selfhost',
        'DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m unittest discover -s tests -v',
        'DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python selfhost/verify.py build/memory-selfhost/glyphc',
        'DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m benchmarks.memory_suite --baseline build/memory-baseline --samples 7',
        'DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m benchmarks.memory_validation',
        'DEVELOPER_DIR=/Library/Developer/CommandLineTools .venv/bin/python -m benchmarks.compiler_memory_measurements',
        '.venv/bin/python -m benchmarks.memory_profile',
        '.venv/bin/python -m benchmarks.memory_report',
        '.venv/bin/python -m benchmarks.memory_delivery',
        '```','',
        'OS process inspection/local socket tests may require running outside a restricted sandbox. Full baseline/current runtime, reduction, record and concurrency suite results are retained alongside [the paired matrix](comparison/results.json). The baseline archive plus `implementation-overlay.tar.gz` reconstruct the sources. `release/profiles-and-c.tar.gz` preserves generated C and raw/merged profiles, and `manifest.json` records file hashes; `preliminary-results.tar.gz` is explicitly superseded.'
    ]
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n');print(OUT/'REPORT.md')
if __name__=='__main__':main()
