#!/usr/bin/env python3
"""Builds a random smoke-test dataset spread across benchmark classes.

The organizer-provided loaders (`clarify.data.preprocess_benchmark`, used by
both `generate_responses.py --dataset_path` and `evaluate_responses.py
--benchmark_path`) only accept a single task class (Mbpp xor HumanEval) per
file -- see the `assert len(tasks) == 1` in `preprocess_benchmark`. So a
"two-class" smoke run can't be one shared dataset file; this script writes
one jsonl file per class instead, and scripts/evaluate.sh runs
generation/evaluation once per class and merges the results.

Only task_id + prompt are written (same shape as the existing
data/mbpp_demo_test.jsonl) -- preprocess_benchmark re-derives everything else
(entry_point, hidden tests, ...) from evalplus's own canonical data, keyed by
task_id.

`--source original` (default) samples only the unperturbed `*_original.jsonl`
files. Those tasks are NOT representative of the leaderboard: none of them get
hidden requirements from data/clarifications.jsonl, so the simulated human falls
back to the reference prompt and asking a question can almost never pay off.
`--source val` instead samples (task_id, prompt) rows of the official validation
split across every perturbation file, exactly as `--split val` loads them, so
generate_responses.py attaches each row's real hidden requirements and the
sample keeps val's mix of clean (~25%) and needs-clarification (~75%) tasks.
One random perturbation is kept per task_id (val has 60 Mbpp and 30 HumanEval
ids), since a single dataset file cannot hold two rows with the same task_id.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The unperturbed variant file for each class -- the same one
# data/mbpp_demo_test.jsonl was itself drawn from.
CANONICAL_FILE = {
    "Mbpp": REPO_ROOT / "data" / "mbpp" / "mbpp_original.jsonl",
    "HumanEval": REPO_ROOT / "data" / "humaneval" / "humaneval_original.jsonl",
}

# Every perturbation file for each class, as clarify.data.load_split reads them.
VARIANT_DIR = {
    "Mbpp": REPO_ROOT / "data" / "mbpp",
    "HumanEval": REPO_ROOT / "data" / "humaneval",
}

VAL_SPLIT = REPO_ROOT / "data" / "splits" / "validation.txt"


def _load_rows(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _val_rows(class_name: str) -> list[dict]:
    """All validation-split rows of one class, across every perturbation file, deduplicated."""
    with VAL_SPLIT.open() as f:
        val_ids = {line.strip() for line in f if line.strip()}

    rows: dict[tuple[str, str], dict] = {}
    for path in sorted(VARIANT_DIR[class_name].glob("*.jsonl")):
        for row in _load_rows(path):
            if row["task_id"] in val_ids and row.get("prompt"):
                rows.setdefault((row["task_id"], row["prompt"]), row)
    return list(rows.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60, help="Total tasks across all classes combined")
    ap.add_argument("--classes", default="Mbpp,HumanEval")
    ap.add_argument(
        "--seed", type=int, default=None, help="Omit for a fresh random sample every call"
    )
    ap.add_argument("--out-dir", default="data/smoke")
    ap.add_argument(
        "--source",
        choices=["original", "val"],
        default="original",
        help="original: unperturbed tasks only; val: the validation split's real task mix",
    )
    args = ap.parse_args()

    classes = [c.strip() for c in args.classes.split(",") if c.strip()]
    for c in classes:
        if c not in CANONICAL_FILE:
            raise ValueError(f"Unknown class `{c}`; known classes: {sorted(CANONICAL_FILE)}")

    rng = random.Random(args.seed)

    per_class, remainder = divmod(args.n, len(classes))

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    written_paths: list[str] = []
    for i, class_name in enumerate(classes):
        if args.source == "val":
            # preprocess_benchmark keys a file's tasks by task_id, so two variants of the same
            # task in one file would silently collapse into one: keep one random variant per id.
            rows = _val_rows(class_name)
            rng.shuffle(rows)
            rows = list({row["task_id"]: row for row in reversed(rows)}.values())
        else:
            rows = _load_rows(CANONICAL_FILE[class_name])
        k = min(per_class + (1 if i < remainder else 0), len(rows))
        sample = rng.sample(rows, k)

        out_path = out_dir / f"{class_name.lower()}_smoke.jsonl"
        with out_path.open("w") as f:
            for row in sample:
                # Carry entry_point/test_cases through, not just task_id+prompt: a
                # chunk of mbpp_original.jsonl's task_ids (anything outside
                # evalplus's own, smaller Mbpp-plus subset) is only reachable
                # through preprocess_benchmark()'s "else" branch, which keeps
                # whatever fields our row already has instead of merging them in
                # from evalplus's canonical dataset -- entry_point must already
                # be present or init_evalplus_evaluator() raises KeyError.
                if args.source == "val":
                    # Keep the row exactly as load_split sees it, so its prompt matches
                    # data/clarifications.jsonl and the real hidden requirements attach.
                    f.write(json.dumps(row) + "\n")
                    continue
                out_row = {"task_id": row["task_id"], "prompt": row["prompt"]}
                if "entry_point" in row:
                    out_row["entry_point"] = row["entry_point"]
                if "test_cases" in row:
                    out_row["test_cases"] = row["test_cases"]
                f.write(json.dumps(out_row) + "\n")

        rel_path = (
            out_path.relative_to(REPO_ROOT) if out_path.is_relative_to(REPO_ROOT) else out_path
        )
        written_paths.append(str(rel_path))
        print(f"{class_name}: wrote {k} tasks to {rel_path}", file=sys.stderr)

    # stdout carries ONLY the final space-separated path list, so a caller
    # can capture it with a plain `$(...)` without parsing the status lines above.
    print(" ".join(written_paths))


if __name__ == "__main__":
    main()
