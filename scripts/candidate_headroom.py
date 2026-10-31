#!/usr/bin/env python3
"""Offline: how often does one of v7's candidates pass while the returned code fails?

Dev tooling (not part of the submission). Reads a run made with `scripts/candidate_dump.py`
(its generate.jsonl and results.jsonl) and the candidate dump. For every candidate position k
writes a generation file where each recorded task returns candidate k (the other tasks keep the
returned code), scores it with evaluate_responses.py (official Docker tests, no LLM call), and
compares per task: returned code vs. each candidate vs. "any candidate passes" (the ceiling of
a perfect selector, before repair).

Usage:
  uv run python scripts/candidate_headroom.py results/runs/<run> results/candidates/<dump>.jsonl \
      OUT_DIR [--split val] [--max-workers 8]
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import subprocess
from pathlib import Path


def rows(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def sha(prompt: str) -> str:
    return hashlib.sha256(prompt.strip().encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("dump")
    parser.add_argument("out")
    parser.add_argument("--split", default="val")
    parser.add_argument("--max-workers", default="8")
    args = parser.parse_args()

    run, out = Path(args.run), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    generations = rows(run / "generate.jsonl")
    returned = {(r["task_id"], sha(r["prompt"])): r["success"] for r in rows(run / "results.jsonl")}
    dump = {r["prompt_sha"]: r for r in rows(Path(args.dump))}
    width = max(len(r["codes"]) for r in dump.values())

    passed: dict[int, dict[tuple, bool]] = {}
    for k in range(width):
        gen_path, res_path = out / f"cand_{k}.jsonl", out / f"cand_{k}_results.jsonl"
        if not res_path.exists():
            with gen_path.open("w") as f:
                for g in generations:
                    record = dump.get(sha(g["prompt"]))
                    if record and k < len(record["codes"]):
                        g = {**g, "prompt_result": record["codes"][k]}
                    f.write(json.dumps(g) + "\n")
            subprocess.run(
                ["uv", "run", "python", "evaluate_responses.py", "--generation_path", gen_path,
                 "--output_path", res_path, "--max_workers", args.max_workers, "--force_rerun",
                 "--split", args.split],
                check=True, stdout=subprocess.DEVNULL,
            )  # fmt: skip
        passed[k] = {(r["task_id"], sha(r["prompt"])): r["success"] for r in rows(res_path)}

    counts = collections.Counter()
    lost = []
    for (task_id, key), ok in returned.items():
        record = dump.get(key)
        if not record:
            counts["not recorded"] += 1
            continue
        cands = [passed[k][(task_id, key)] for k in range(len(record["codes"]))]
        chosen = record["chosen"]
        repaired = chosen is None or record["final"] != record["codes"][chosen]
        counts["recorded"] += 1
        counts["returned passes"] += ok
        counts["any candidate passes"] += ok or any(cands)
        counts[f"passing candidates {sum(cands)}/{len(cands)}"] += 1
        counts["repaired (returned != chosen)"] += repaired
        for k, c in enumerate(cands):
            counts[f"candidate {k} passes"] += c
        majority = sum(cands) * 2 > len(cands)
        counts["majority of candidates pass"] += majority
        if not ok and any(cands):
            lost.append(
                {"task_id": task_id, "chosen": chosen, "repaired": repaired, "cands": cands}
            )
            counts["returned fails, a candidate passes"] += 1
            counts["  ... of which repaired"] += repaired
        if ok and not any(cands):
            counts["returned passes, no candidate does (repair won)"] += 1
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")
    with (out / "lost.jsonl").open("w") as f:
        for item in lost:
            f.write(json.dumps(item) + "\n")


if __name__ == "__main__":
    main()
