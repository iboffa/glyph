"""Run memory comparison/release experiments sequentially to avoid timing overlap."""
import argparse, sys
from pathlib import Path
from . import memory_improvements,release_workflow,allocator_experiment,precise_experiment,runtime,reductions,records,concurrency
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline',type=Path,required=True)
    ap.add_argument('--samples',type=int,default=7)
    args=ap.parse_args();samples=str(args.samples)
    sys.argv=['memory_improvements','--baseline',str(args.baseline.resolve()),'--samples',samples];memory_improvements.main()
    for frontend in ('reference','native'):
        for compiler in (False,True):
            sys.argv=['release_workflow','--frontend',frontend,'--samples',samples]+(['--compiler-workload'] if compiler else [])
            release_workflow.main()
    allocator_experiment.main()
    precise_experiment.main()
    current=ROOT/'benchmarks/results/macos-arm64-2026-10-28-memory/current';current.mkdir(parents=True,exist_ok=True)
    runtime.OUT=current;sys.argv=['runtime','--samples','5'];runtime.main()
    sys.argv=['reductions','--samples','5','--output',str(current/'reductions.json')];reductions.main()
    sys.argv=['records','--samples','5','--output',str(current/'records.json')];records.main()
    sys.argv=['concurrency','--samples','5','--output-dir',str(current/'concurrency')];concurrency.main()
if __name__=='__main__':main()
