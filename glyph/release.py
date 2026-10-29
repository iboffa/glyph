"""Validated Clang release options shared by the Python driver and workflows."""
from pathlib import Path
from .syntax import Diagnostic, Token

def flags(lto='none', cpu='portable', profile_generate=None, profile_use=None, stats=False, zero_init=False, gc_timing=False):
    def error(text):
        raise Diagnostic('G204', text, Token('', 1, 1, 1))
    if lto not in {'none', 'thin', 'full'} or cpu not in {'portable', 'native'}:
        error('unsupported release target/LTO mode')
    if profile_generate and profile_use:
        error('profile generation and use are mutually exclusive')
    result = []
    if lto != 'none':
        result.append('-flto=' + lto)
    if cpu == 'native':
        import platform
        result.append('-mcpu=native' if platform.machine() in {'arm64', 'aarch64'} else '-march=native')
    if profile_generate:
        result.append('-fprofile-instr-generate=' + str(Path(profile_generate).resolve()))
    if profile_use:
        path = Path(profile_use).resolve()
        if not path.is_file():
            error('merged profile does not exist: ' + str(path))
        result += ['-fprofile-instr-use=' + str(path), '-Werror=profile-instr-out-of-date', '-Werror=profile-instr-unprofiled']
    if stats:
        result.append('-DGLYPH_ALLOC_STATS')
    if gc_timing:
        import sys
        if sys.platform not in {'darwin', 'linux'}:
            error('GC event timing requires POSIX thread CPU clocks')
        result.append('-DGLYPH_GC_TIMING')
    if zero_init:
        result.append('-DGLYPH_ZERO_INIT')
    return result
