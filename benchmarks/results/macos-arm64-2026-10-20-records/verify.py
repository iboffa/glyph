"""Reproduce the record feature's native correctness verification."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
os.chdir(ROOT)
if os.environ.get("GLYPH_SKIP_EXECUTION") == "1":
    raise SystemExit("Native verification requires execution enabled")


def now():
    return datetime.now(ZoneInfo("Europe/Vilnius")).isoformat()


inputs = [p for folder in ("glyph", "tests") for p in (ROOT / folder).glob("*.py")]
inputs += list((ROOT / "glyph").glob("*.h"))
inputs += list((ROOT / "examples").glob("*.gly"))
inputs += [ROOT / "docs/AGENT_GUIDE.md", Path(__file__).resolve()]
record = {
    "started_at": now(),
    "platform": platform.platform(),
    "python": sys.version,
    "base_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "worktree_has_changes": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
    "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(inputs)},
    "developer_dir": os.environ.get("DEVELOPER_DIR"),
    "sdk": subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip(),
    "scope": "Native correctness and CLI verification; no new speed or AI-cost measurements.",
    "steps": {},
}
commands = {
    "tests": [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    "format": [sys.executable, "-m", "glyph", "fmt", "examples/records.gly", "--check"],
    "example": [sys.executable, "-m", "glyph", "run", "examples/records.gly"],
    "diff_check": ["git", "diff", "--check"],
}
for name, command in commands.items():
    result = subprocess.run(command, capture_output=True, text=True)
    (OUT / (name + ".log")).write_text(result.stdout + result.stderr)
    record["steps"][name] = {"command": command, "exit_code": result.returncode}
    print(name, result.returncode, flush=True)
    print(result.stdout + result.stderr, flush=True)
record["finished_at"] = now()
(OUT / "verification.json").write_text(json.dumps(record, indent=2) + "\n")
raise SystemExit(int(any(s["exit_code"] for s in record["steps"].values())))
