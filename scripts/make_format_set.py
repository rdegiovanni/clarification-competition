#!/usr/bin/env python3
"""The val variants whose prompt states a return format, as evaluation datasets.

Dev tooling (not part of the submission). Selects, from the validation split's variants (every
perturbation file, as `--split val` loads them), the prompts that match the algorithm's own
RETURN_FORMAT_STATEMENT trigger of `format_question`, and writes one dataset file per class, in
the format of data/<class>/*.jsonl. Nothing but the prompt text is used to select.

Usage:
  uv run python -m scripts.make_format_set results/format_sets
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from clarify.algorithms.laaser_pinpoint_smt_3 import RETURN_FORMAT_STATEMENT

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()
    val = set((REPO_ROOT / "data" / "splits" / "validation.txt").read_text().split())
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for cls in ("mbpp", "humaneval"):
        seen, rows = set(), []
        for path in sorted((REPO_ROOT / "data" / cls).glob("*.jsonl")):
            for line in path.read_text().splitlines():
                row = json.loads(line) if line.strip() else None
                if not row or row["task_id"] not in val or not row.get("prompt"):
                    continue
                key = (row["task_id"], row["prompt"])
                if key not in seen and RETURN_FORMAT_STATEMENT.search(row["prompt"]):
                    seen.add(key)
                    rows.append(row)
        out = args.out_dir / f"{cls}_format.jsonl"
        out.write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(f"{out}: {len(rows)} variants")


if __name__ == "__main__":
    main()
