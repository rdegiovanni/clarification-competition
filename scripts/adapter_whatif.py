#!/usr/bin/env python3
"""Offline what-if: our call adapter (`call_adapter` in laaser_pinpoint_smt_3.py) on a run's code.

Dev tooling (not part of the submission). Appends CALL_ADAPTER to the code of every task of a
run's generate.jsonl and writes a new generation file for evaluate_responses.py, so the same
code is scored with and without it: no LLM call, no sampling noise.

Usage:
  PYTHONPATH=. uv run python scripts/adapter_whatif.py results/runs/<run>/generate.jsonl OUT.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from clarify.algorithms.laaser_pinpoint_smt_3 import call_adapter

REPO_ROOT = Path(__file__).resolve().parent.parent


def entry_points() -> dict[str, str]:
    found = {}
    for path in (REPO_ROOT / "data").glob("*/*_original.jsonl"):
        for line in path.open():
            if line.strip():
                row = json.loads(line)
                found[row["task_id"]] = row["entry_point"]
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("generation")
    parser.add_argument("out")
    args = parser.parse_args()

    entries = entry_points()
    touched = 0
    with open(args.generation) as src, open(args.out, "w") as dst:
        for line in src:
            if not line.strip():
                continue
            row = json.loads(line)
            code = row.get("prompt_result") or ""
            adapted = call_adapter(code, entries.get(row["task_id"], ""))
            touched += adapted != code
            row["prompt_result"] = adapted
            dst.write(json.dumps(row) + "\n")
    print(f"adapter appended to {touched} implementations")


if __name__ == "__main__":
    main()
