#!/usr/bin/env python3
"""Tasks whose outcome flips between runs of the same algorithm file on the same smoke set.

Dev tooling (not part of the submission). Reads results/history.csv, keeps the runs of one
smoke set (default: smoke-70 from val, gpt-4.1-mini, the set every recent run used), and for
each algorithm file prints how many tasks always pass, always fail or flip. With
--write-dataset it writes the flipping tasks of the chosen files, with exactly the prompts the
smoke runs used, as one dataset per benchmark class (for `scripts/evaluate.sh --dataset-path`).

Usage:
  uv run python scripts/find_flaky_tasks.py
  uv run python scripts/find_flaky_tasks.py --write-dataset results/flaky_sets \
      --files laaser_pinpoint.py laaser_pinpoint_smt.py laaser_pinpoint_smt_3.py
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH = REPO_ROOT / "results" / "history.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-tasks", default="70")
    parser.add_argument("--dataset-contains", default="source=val")
    parser.add_argument("--model", default="openai/gpt-4.1-mini")
    parser.add_argument("--files", nargs="*", help="algorithm file names whose flips to write")
    parser.add_argument("--write-dataset", type=Path, help="directory for <class>_flaky.jsonl")
    args = parser.parse_args()

    rows = [
        r
        for r in csv.DictReader(HISTORY_PATH.open())
        if r["n_tasks"] == args.n_tasks
        and args.dataset_contains in r["dataset"]
        and r["model"] == args.model
    ]
    outcomes = collections.defaultdict(lambda: collections.defaultdict(list))
    smoke_dirs = []
    for r in rows:
        run_dir = REPO_ROOT / r["run_dir"]
        results = run_dir / "results.jsonl"
        if not results.exists():
            continue
        smoke_dirs.append(run_dir / "smoke_data")
        for line in results.open():
            task = json.loads(line)
            outcomes[Path(r["clarify_py"]).name][task["task_id"]].append(bool(task["success"]))

    flipping_union: set[str] = set()
    for name, tasks in outcomes.items():
        runs = max(len(v) for v in tasks.values())
        flips = sorted(t for t, v in tasks.items() if 0 < sum(v) < len(v))
        print(
            f"{name}: runs={runs} always_pass={sum(all(v) for v in tasks.values())} "
            f"always_fail={sum(not any(v) for v in tasks.values())} flipping={len(flips)}"
        )
        print("   ", " ".join(f"{t}({sum(tasks[t])}/{len(tasks[t])})" for t in flips))
        if not args.files or name in args.files:
            flipping_union.update(flips)

    if args.write_dataset:
        smoke = next((d for d in smoke_dirs if d.is_dir()), None)
        if smoke is None:
            raise SystemExit("no smoke_data directory found in the selected runs")
        args.write_dataset.mkdir(parents=True, exist_ok=True)
        for path in sorted(smoke.glob("*_smoke.jsonl")):
            kept = [line for line in path.open() if json.loads(line)["task_id"] in flipping_union]
            out = args.write_dataset / path.name.replace("_smoke", "_flaky")
            out.write_text("".join(kept))
            print(f"wrote {len(kept)} tasks to {out}")


if __name__ == "__main__":
    main()
