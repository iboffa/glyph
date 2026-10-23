"""Build the bundled, single-threaded BDWGC without a system GC dependency."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

from .syntax import Diagnostic, Token


VENDOR = Path(__file__).with_name("vendor") / "bdwgc"


def include_flags():
    return ["-I" + str(VENDOR / "include"), "-DGC_NOT_DLL"]


def collector_flags(target=None):
    target = target or sys.platform
    flags = include_flags() + ["-std=c11", "-O2", "-fno-strict-aliasing",
                              "-DGC_BUILTIN_ATOMIC", "-DALL_INTERIOR_POINTERS",
                              "-DNO_EXECUTE_PERMISSION", "-DGC_DISABLE_INCREMENTAL"]
    if target == "darwin":
        # AppKit loads more Mach-O root ranges than the upstream default 2048.
        flags += ["-D_DARWIN_C_SOURCE", "-DLARGE_CONFIG"]
    elif target.startswith("linux"):
        flags += ["-D_GNU_SOURCE"]
    return flags


def collector_object(cc, cache, env):
    """Cache by source, compiler, host and SDK; publish only finished objects."""
    flags = collector_flags()
    version = subprocess.run(cc + ["--version"], capture_output=True, env=env)
    if version.returncode:
        raise Diagnostic("G202", "cannot identify native compiler for GC build", Token("", 1, 1, 1))
    digest = hashlib.sha256()
    for path in sorted(VENDOR.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(VENDOR)).encode())
            digest.update(path.read_bytes())
    config = [cc, flags, platform.platform(), platform.machine(),
              {key: env.get(key) for key in ("SDKROOT", "DEVELOPER_DIR", "MACOSX_DEPLOYMENT_TARGET", "PATH")}]
    digest.update(json.dumps(config, sort_keys=True).encode())
    digest.update(version.stdout)
    destination = cache / ("bdwgc-" + digest.hexdigest() + ".o")
    if destination.exists():
        return destination
    fd, temporary = tempfile.mkstemp(prefix="bdwgc-", suffix=".o", dir=cache)
    os.close(fd)
    try:
        command = cc + flags + ["-c", str(VENDOR / "extra/gc.c"), "-o", temporary]
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        if result.returncode:
            raise Diagnostic("G202", "bundled GC build failed: " + result.stderr[-4000:], Token("", 1, 1, 1))
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination
