"""Run the documented verification, keeping this host's artifacts together."""
import contextlib
from datetime import datetime
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
if os.environ.get("GLYPH_SKIP_EXECUTION") == "1":
    raise SystemExit("Native verification requires execution enabled")

record = {
    "started_at": datetime.now().astimezone().isoformat(),
    "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "developer_dir": os.environ.get("DEVELOPER_DIR"),
    "sdk": subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip(),
    "steps": {},
}
command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
with (OUT / "tests.log").open("w") as log:
    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
record["steps"]["tests"] = result.returncode
print((OUT / "tests.log").read_text(), flush=True)

for name in ("codegen", "agent", "runtime", "report"):
    print("Running", name, flush=True)
    module = importlib.import_module("benchmarks." + name)
    module.OUT = OUT
    sys.argv = ["benchmarks." + name] + (["--samples", "5"] if name == "runtime" else [])
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

record["finished_at"] = datetime.now().astimezone().isoformat()
(OUT / "verification.json").write_text(json.dumps(record, indent=2) + "\n")
raise SystemExit(int(any(record["steps"].values())))
