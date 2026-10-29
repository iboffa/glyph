import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from . import __version__
from .syntax import parse, Diagnostic, Token
from .checker import check
from .backend import Emitter, compile_c
from .formatter import format_source
from .modules import load_program


def main(argv=None):
    parser = argparse.ArgumentParser(prog="glyph")
    parser.add_argument("--version", action="version", version="Glyph " + __version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "build", "run", "fmt"):
        p = commands.add_parser(name)
        p.add_argument("source", type=Path)
        p.add_argument("--json", action="store_true", help="emit JSON Lines diagnostics")
        if name != "fmt":
            p.add_argument("--opt-report", type=Path)
            p.add_argument("--no-optimize", action="store_true")
        if name in {"build", "run"}:
            p.add_argument("-o", "--output", type=Path)
            p.add_argument("-O", choices=["0", "1", "2", "3"], default="2")
            p.add_argument("--emit-c", type=Path)
            p.add_argument("--cc", type=Path)
            p.add_argument("--lto", choices=['none', 'thin', 'full'], default='none')
            p.add_argument("--cpu", choices=['portable', 'native'], default='portable')
            p.add_argument("--profile-generate", type=Path)
            p.add_argument("--profile-use", type=Path)
            p.add_argument("--alloc-stats", action='store_true')
            p.add_argument("--gc-timing", action='store_true')
            p.add_argument("--zero-init", action='store_true')
        if name == "fmt":
            p.add_argument("--check", action="store_true")
    argv = list(sys.argv[1:] if argv is None else argv)
    runtime_args = []
    if "--" in argv:
        i = argv.index("--")
        runtime_args, argv = argv[i + 1:], argv[:i]
    args = parser.parse_args(argv)
    try:
        if runtime_args and args.command != "run":
            raise Diagnostic("G004", "program arguments require glyph run", Token("", 1, 1, 1))
        if args.source.suffix != ".gly":
            raise Diagnostic("G004", "source file must have .gly extension", Token("", 1, 1, 1))
        source = args.source.read_text(encoding="utf-8")
        if args.command == "fmt":
            formatted = format_source(source)
            if args.check and source != formatted:
                raise Diagnostic("G301", "source is not canonically formatted", Token("", 1, 1, 1))
            if not args.check:
                args.source.write_text(formatted, encoding="utf-8", newline="\n")
            return 0
        program = load_program(args.source)
        functions = check(program)
        if args.opt_report:
            from .analysis import Analysis
            report = args.opt_report.resolve()
            if any(report == p or report.exists() and report.samefile(p) for p in program.paths):
                raise Diagnostic("G004", "report must not overwrite a source", Token("", 1, 1, 1))
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(Analysis(functions, not args.no_optimize).report_data(), indent=2) + "\n")
        if args.command == "check":
            return 0
        output = args.output or Path("build") / (args.source.stem + (".exe" if os.name == "nt" else ""))
        output = output.resolve()
        cpath = args.emit_c or output.with_suffix(".c")
        cpath = cpath.resolve()
        def aliases(a, b):
            return a == b or a.exists() and b.exists() and a.samefile(b)
        if aliases(cpath, output) or any(aliases(target, p) for target in (output, cpath) for p in program.paths):
            raise Diagnostic("G004", "source, generated C and executable paths must differ", Token("", 1, 1, 1))
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(Emitter(optimize=not args.no_optimize).emit(functions, args.source), encoding="utf-8")
        compile_c(cpath, output, args.O, cc_override=args.cc, lto=args.lto, cpu=args.cpu, profile_generate=args.profile_generate, profile_use=args.profile_use, stats=args.alloc_stats, gc_timing=args.gc_timing, zero_init=args.zero_init or args.no_optimize)
        if args.command == "run":
            return subprocess.run([str(output), *runtime_args]).returncode
        return 0
    except Diagnostic as error:
        if args.json:
            print(json.dumps(error.record(args.source), ensure_ascii=False), file=sys.stderr)
        else:
            t = error.token
            print(f"{t.path or args.source}:{t.line}:{t.col}: {error.code}: {error.message}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError) as error:
        d = Diagnostic("G200", str(error), Token("", 1, 1, 1))
        print(json.dumps(d.record(args.source)) if args.json else f"G200: {error}", file=sys.stderr)
        return 1
    except (RecursionError, ValueError) as error:
        # Malformed huge integers/deep expressions are input errors, never tracebacks.
        d = Diagnostic("G005", "source exceeds frontend nesting or literal limits", Token("", 1, 1, 1))
        print(json.dumps(d.record(args.source)) if args.json else f"G005: {d.message}", file=sys.stderr)
        return 1
