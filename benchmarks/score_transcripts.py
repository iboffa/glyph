"""Score externally recorded agent trials without fabricating missing costs.

Input JSONL: {task, language, model, success: bool, events: [{kind,text}],
             retries: int, billed_total_tokens?: int}.
Events must include every visible prompt, instruction, response and tool result,
including retransmitted history. Billing/reasoning costs require provider usage.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import tiktoken


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("transcripts", type=Path)
    args = parser.parse_args()
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(__file__).resolve().parents[1] / ".tmp" / "tiktoken"))
    enc = tiktoken.get_encoding("cl100k_base")
    groups = {}
    for line in args.transcripts.read_text(encoding="utf-8").splitlines():
        trial = json.loads(line)
        if type(trial["success"]) is not bool or not trial["events"] or trial["retries"] < 0:
            raise ValueError("incomplete trial")
        total = sum(len(enc.encode(e["text"], disallowed_special=())) for e in trial["events"])
        group = groups.setdefault(trial["language"], [])
        group.append({"task": trial["task"], "model": trial["model"], "success": trial["success"], "visible_tokens": total,
                      "retries": trial["retries"], "billed_total_tokens": trial.get("billed_total_tokens")})
    report = {}
    for language, trials in groups.items():
        successes = sum(t["success"] for t in trials)
        report[language] = {"trials": trials, "successes": successes, "attempted_tasks": len(trials),
            "visible_tokens_per_correct_task_including_failures": sum(t["visible_tokens"] for t in trials)/successes if successes else None,
            "mean_retries": statistics.mean(t["retries"] for t in trials),
            "billed_tokens_per_correct_task": sum(t["billed_total_tokens"] for t in trials)/successes if successes and all(t["billed_total_tokens"] is not None for t in trials) else None}
    print(json.dumps({"tokenizer": "cl100k_base", "results": report}, indent=2))


if __name__ == "__main__":
    main()
