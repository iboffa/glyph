"""Inspect optimized LLVM for imperative/fold reductions without executing binaries."""
import json
import os
from pathlib import Path
import re
import subprocess
from collections import Counter
from glyph.syntax import parse, Token
from glyph.checker import check
from glyph.gc_support import include_flags
from glyph.backend import Emitter, compiler
from .runtime import BUILD, OUT, ROOT


def main():
    bodies = {"loop": "reduce a:[i64]>i64\n  s:i64 = 0\n  for x:a\n    s += x\n  ret s\n",
              "fold": "reduce a:[i64]>i64 = fold a 0 +\n",
              "sum": "reduce a:[int] = sum(a)\n"}
    BUILD.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    functions = {}
    for name, source in bodies.items():
        ast = check(parse(source + "\nmain>void\n  ret\n"))
        # Match diagnostic locations so only lowering shape is compared.
        def normalize(node):
            if hasattr(node, "token"):
                node.token = Token("", 1, 1, 2)
            for attr in ["args", "body", "other"]:
                for child in getattr(node, attr, []):
                    normalize(child)
        for f in ast:
            normalize(f)
        text = Emitter().emit(ast, "reduction.gly").replace("static int64_t f_reduce", "int64_t f_reduce")
        c = BUILD / ("inspect_" + name + ".c")
        ir = c.with_suffix(".ll")
        c.write_text(text)
        env = os.environ.copy()
        cache = ROOT / "build" / ".glyph-cache"
        cache.mkdir(parents=True, exist_ok=True)
        env.update(ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache), TEMP=str(cache), TMP=str(cache))
        command = compiler() + include_flags() + [str(c), "-std=c11", "-O2", "-g0", "-S", "-emit-llvm", "-fno-fast-math", "-ffp-contract=off", "-o", str(ir)]
        if os.name != "nt":
            command += ["-D_POSIX_C_SOURCE=200809L"]
        subprocess.run(command, check=True, capture_output=True, env=env)
        raw = ir.read_text()
        body = re.search(r"^define[^\n]*@f_reduce\([^\n]*\n.*?^\}", raw, re.M | re.S).group(0)
        body = re.sub(r"![\w.]+ !\d+", "!metadata !N", body)
        body = re.sub(r"#\d+", "#ATTR", body)
        functions[name] = body
        (OUT / ("reduce_" + name + ".ll.txt")).write_text(body + "\n")
    equal = functions["loop"] == functions["fold"]
    def opcodes(body):
        result = Counter()
        for line in body.splitlines()[1:-1]:
            line = line.strip()
            if not line or re.match(r"\d+:", line):
                continue
            instruction = re.sub(r"^%\d+ = ", "", line)
            result[instruction.split()[0]] += 1
        return dict(sorted(result.items()))
    counts = {name: opcodes(body) for name, body in functions.items()}
    result = {"equal_optimized_function_ir": equal, "opcode_counts": counts, "equal_opcode_counts": counts["loop"] == counts["fold"],
              "sum_matches_fold_opcode_counts": counts["sum"] == counts["fold"],
              "method": "Clang -O2 LLVM function IR; exported reduce; identical source-span locations; metadata/attribute indices normalized; no native execution",
              "scope": "i64 fold and sum use guarded reduction; explicit loops retain per-add checks; opcode counts are structural evidence, not a semantic proof or runtime measurement"}
    (OUT / "codegen.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if counts["sum"] != counts["fold"]:
        raise SystemExit("sum/fold code shape differs; inspect optimizer output")


if __name__ == "__main__":
    main()
