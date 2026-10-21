#!/usr/bin/env python3
"""The tasks of a smoke run with at least N hidden requirements, as evaluation datasets.

Dev tooling (not part of the submission). With one clarification turn, tasks with two or more
hidden requirements are where the score is lost (v7 on smoke-70: 1 requirement 22/23 passed,
2+ only 10/24), so variants that target them are measured on this subset first.

data/clarifications.jsonl is read ONLY to count the (question, answer) pairs of each task and
choose which tasks to evaluate; no requirement text is used, and nothing here reaches an
algorithm.

Usage:
  uv run python scripts/make_multireq_set.py results/runs/<smoke run> results/multireq_sets
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path, help="a smoke run with a smoke_data/ directory")
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--min-requirements", type=int, default=2)
    args = parser.parse_args()

    counts = {}  # keyed on the stripped prompt: generate_responses.py appends "\n" to MBPP's
    for line in (REPO_ROOT / "data" / "clarifications.jsonl").open():
        row = json.loads(line)
        counts[(row["task_id"], row["prompt"].strip())] = len(row["clarifications"]) // 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted((args.run_dir / "smoke_data").glob("*_smoke.jsonl")):
        kept = [
            line
            for line in path.open()
            if counts.get((json.loads(line)["task_id"], json.loads(line)["prompt"].strip()), 0)
            >= args.min_requirements
        ]
        out = args.out_dir / path.name.replace("_smoke", "_multireq")
        out.write_text("".join(kept))
        print(f"wrote {len(kept)} tasks to {out}")


if __name__ == "__main__":
    main()
