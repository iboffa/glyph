"""Reproduce this host's verification without overwriting the earlier baseline."""
import contextlib
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
if os.environ.get("GLYPH_SKIP_EXECUTION") == "1":
    raise SystemExit("Native verification requires execution enabled")


def now():
    return datetime.now(ZoneInfo("Europe/Vilnius")).isoformat()


inputs = [p for folder in ("glyph", "tests", "benchmarks") for p in (ROOT / folder).glob("*.py")]
inputs += list((ROOT / "glyph").glob("*.h"))
inputs += list((ROOT / "examples").glob("*.gly"))
inputs += list((ROOT / "benchmarks/programs").iterdir())
inputs += [ROOT / "docs/AGENT_GUIDE.md"]
record = {
    "started_at": now(),
    "base_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "worktree_has_changes": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
    "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(inputs) if p.is_file()},
    "developer_dir": os.environ.get("DEVELOPER_DIR"),
    "sdk": subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip(),
    "runtime_process_inspection": "Process memory sampling requires sysctl access outside the sandbox.",
    "steps": {},
}
command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
with (OUT / "tests.log").open("w") as log:
    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
record["steps"]["tests"] = result.returncode
print((OUT / "tests.log").read_text(), flush=True)

for name in ("codegen", "agent", "runtime", "reductions", "report"):
    print("Running", name, flush=True)
    module = importlib.import_module("benchmarks." + name)
    module.OUT = OUT
    sys.argv = ["benchmarks." + name]
    if name == "runtime":
        sys.argv += ["--samples", "5"]
    elif name == "reductions":
        sys.argv += ["--samples", "15", "--output", str(OUT / "reductions.json")]
    with (OUT / (name + ".log")).open("w") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                module.main()
            except (Exception, SystemExit):
                traceback.print_exc()
                record["steps"][name] = 1
            else:
                record["steps"][name] = 0
    print((OUT / (name + ".log")).read_text(), flush=True)

if record["steps"]["report"] == 0:
    path = OUT / "REPORT.md"
    path.write_text(path.read_text().replace("[../README.md](../README.md)", "[methodology](../../README.md)"))
record["finished_at"] = now()
(OUT / "verification.json").write_text(json.dumps(record, indent=2) + "\n")
raise SystemExit(int(any(record["steps"].values())))
