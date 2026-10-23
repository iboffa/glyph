"""Token inventory and a *scripted* one-repair diagnostic exercise, not an agent trial."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tiktoken
from glyph.backend import compile_c
from glyph.syntax import Diagnostic
from .runtime import ROOT, BUILD, OUT

TASKS = {
    "sum": {
        "prompt": "Implement solve(a), the sum of signed integers. Empty input returns zero. Verify [1, -2, 4] -> 3, [] -> 0. Test inputs do not overflow i64.",
        "glyph": "solve a:[int] = sum(a)\n",
        "python": "def solve(a):\n    return sum(a)\n",
        "c": "int64_t solve(const int64_t *a, int64_t n) {\n    int64_t s = 0;\n    for (int64_t i = 0; i < n; i++) s += a[i];\n    return s;\n}\n",
        "glyph_main": "main>void\n  print(solve([1, -2, 4]))\n  print(solve([]))\n",
        "python_main": "print(solve([1, -2, 4]))\nprint(solve([]))\n",
        "c_main": "int main(void) { int64_t a[] = {1, -2, 4}; printf(\"%lld\\n%lld\\n\", (long long)solve(a, 3), (long long)solve(a, 0)); }\n",
        "expected": "3\n0\n",
    },
    "positive_count": {
        "prompt": "Implement solve(a), counting values strictly greater than zero. Verify [-2, 0, 3, 7] -> 2, [] -> 0. Test inputs fit i64.",
        "glyph": "solve a:[int] = count(x > 0 for x in a)\n",
        "python": "def solve(a):\n    return sum(x > 0 for x in a)\n",
        "c": "int64_t solve(const int64_t *a, int64_t n) {\n    int64_t count = 0;\n    for (int64_t i = 0; i < n; i++) if (a[i] > 0) count++;\n    return count;\n}\n",
        "glyph_main": "main>void\n  print(solve([-2, 0, 3, 7]))\n  print(solve([]))\n",
        "python_main": "print(solve([-2, 0, 3, 7]))\nprint(solve([]))\n",
        "c_main": "int main(void) { int64_t a[] = {-2, 0, 3, 7}; printf(\"%lld\\n%lld\\n\", (long long)solve(a, 4), (long long)solve(a, 0)); }\n",
        "expected": "2\n0\n",
    },
    "dot": {
        "prompt": "Implement solve(a, b), the dot product of equal-length signed integer arrays. Verify [1, 2, 3] and [4, 5, 6] -> 32, two empty arrays -> 0. No operation overflows i64.",
        "glyph": "solve a:[int], b:[int] = sum(x * y for x, y in zip(a, b))\n",
        "python": "def solve(a, b):\n    return sum(x * y for x, y in zip(a, b))\n",
        "c": "int64_t solve(const int64_t *a, const int64_t *b, int64_t n) {\n    int64_t s = 0;\n    for (int64_t i = 0; i < n; i++) s += a[i] * b[i];\n    return s;\n}\n",
        "glyph_main": "main>void\n  print(solve([1, 2, 3], [4, 5, 6]))\n  print(solve([], []))\n",
        "python_main": "print(solve([1, 2, 3], [4, 5, 6]))\nprint(solve([], []))\n",
        "c_main": "int main(void) { int64_t a[] = {1, 2, 3}, b[] = {4, 5, 6}; printf(\"%lld\\n%lld\\n\", (long long)solve(a, b, 3), (long long)solve(a, b, 0)); }\n",
        "expected": "32\n0\n",
    },
}


def execute_trial(lang, path, skip_execution):
    exe = path.with_suffix(".exe" if os.name == "nt" else ".out")
    if lang == "glyph":
        proc = subprocess.run([sys.executable, "-m", "glyph", "build", str(path), "--json", "-o", str(exe)], capture_output=True, text=True, cwd=ROOT)
        if proc.returncode:
            return {"success": False, "diagnostic": proc.stderr, "stdout": proc.stdout}
    elif lang == "c":
        try:
            compile_c(path, exe)
        except Diagnostic as error:
            return {"success": False, "diagnostic": error.message.removeprefix("native backend failed: "), "stdout": ""}
    if skip_execution and lang != "python":
        return {"success": None, "diagnostic": "", "stdout": None, "status": "compiled; native execution blocked by host policy"}
    command = [sys.executable, str(path)] if lang == "python" else [str(exe)]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=20)
    return {"success": proc.returncode == 0, "diagnostic": proc.stderr, "stdout": proc.stdout}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-native-execution", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(ROOT / ".tmp" / "tiktoken"))
    encoder = tiktoken.get_encoding("cl100k_base")
    count = lambda s: len(encoder.encode(s, disallowed_special=()))
    instructions = {"glyph": (ROOT / "docs" / "AGENT_GUIDE.md").read_text(encoding="utf-8"),
                    "c": "Use C11 with int64_t arrays and explicit lengths. Include stdint.h and stdio.h. Compile with clang -std=c11 -O2. Return the result from solve; use printf to verify outputs. Inputs are within the specified non-overflowing domain. Fix compiler errors before running tests.\n",
                    "python": "Use Python 3.11+ with lists of integers and standard builtins. Return the result from solve. Execute with python and verify printed outputs. Fix exceptions before claiming completion.\n"}
    results = {"tokenizer": "cl100k_base", "tiktoken": importlib.metadata.version("tiktoken"),
               "study_type": "hand-authored source inventory and scripted repair; no agent sampled",
               "actual_agent_retries": None, "actual_total_agent_tokens_per_correct_task": None,
               "instruction_tokens": {lang: count(text) for lang, text in instructions.items()}, "tasks": {}}
    BUILD.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, task in TASKS.items():
        results["tasks"][name] = {}
        for lang in ["glyph", "python", "c"]:
            suffix = {"glyph": ".gly", "python": ".py", "c": ".c"}[lang]
            headers = "#include <stdint.h>\n#include <stdio.h>\n" if lang == "c" else ""
            source = headers + task[lang] + "\n" + task[lang + "_main"]
            # Deliberately call an undefined function in the harness. Exactly one repair is scripted.
            marker = {"glyph": "print(solve(", "python": "print(solve(", "c": "(long long)solve("}[lang]
            bad = source.replace(marker, marker.replace("solve", "missing"), 1)
            path = BUILD / ("task_" + name + "_" + lang + suffix)
            path.write_text(bad, encoding="utf-8")
            first = execute_trial(lang, path, args.skip_native_execution)
            if first["success"] is not False:
                raise AssertionError("the deliberately invalid program was not rejected")
            path.write_text(source, encoding="utf-8")
            final = execute_trial(lang, path, args.skip_native_execution)
            if final["success"] is not None:
                final["success"] = final["success"] and final["stdout"] == task["expected"]
                if not final["success"]:
                    raise AssertionError((name, lang, final))
            events = [{"kind": "instructions", "text": instructions[lang]}, {"kind": "task", "text": task["prompt"]},
                      {"kind": "attempt", "text": bad}, {"kind": "diagnostic", "text": first["diagnostic"]},
                      {"kind": "attempt", "text": source}]
            if final["success"]:
                events.append({"kind": "verification", "text": "PASS\n" + final["stdout"]})
            tokens = [{"kind": event["kind"], "tokens": count(event["text"])} for event in events]
            total = sum(event["tokens"] for event in tokens)
            results["tasks"][name][lang] = {"solution_tokens": count(task[lang]), "full_source_tokens": count(source),
                "source_characters": len(source), "diagnostic_tokens": count(first["diagnostic"]), "scripted_retries": 1,
                "visible_transcript_tokens": total, "visible_tokens_per_verified_scripted_task": total if final["success"] else None,
                "verified": final["success"], "final_result": final, "events": events, "event_token_counts": tokens}
            print(name, lang, "solution tokens", count(task[lang]), "verified", final["success"], flush=True)
    (OUT / "agent.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
