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

`--hard-tasks` (default: KNOWN_HARD_TASKS below) force-includes specific
task_ids regardless of the random sample, so every smoke run keeps exercising
the hardest cases on record instead of possibly rolling none of them. The
default list is every task REPORT.md/docs/failure-analysis.md have identified
as failing under nearly every challenger so far: the "universal failures" set
(`HumanEval/139, Mbpp/143, Mbpp/26, Mbpp/229, Mbpp/559, Mbpp/759`) plus the
rest of the same (arr, n)-style redundant-signature class (`Mbpp/617, Mbpp/888`)
and the GateV3-era regression (`Mbpp/90`). Pass `--hard-tasks ""` to disable
and fall back to a fully random sample. The rest of each class's quota is
still filled randomly as before.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Tasks REPORT.md / docs/failure-analysis.md have identified as failing under nearly every
# challenger measured so far (the "universal failures" set, the wider (arr, n)-signature class,
# and the one known challenger-induced regression) -- force-included by default so a 70-task
# smoke run keeps exercising the hardest known cases instead of possibly rolling none of them.
KNOWN_HARD_TASKS = [
    "Mbpp/26",  # check_k_elements: ambiguous "k elements" reading (tuple-length vs. all-equal-k)
    "Mbpp/229",  # re_arrange_array: unmentioned second arg `n`, (arr, n)-style MBPP convention
    "Mbpp/559",  # max_sub_array_sum: same (arr, n) redundant-length-argument convention
    "Mbpp/617",  # same (arr, n) convention gap, surfaced in the wider failure-analysis refresh
    "Mbpp/888",  # same (arr, n) convention gap, surfaced in the wider failure-analysis refresh
    "Mbpp/143",  # universal failure across all challengers measured so far
    "Mbpp/759",  # universal failure across all challengers measured so far
    "Mbpp/90",  # regression: Gate-family variants assume *dicts/wrong input type here
    "HumanEval/139",  # special_factorial: host-side int-to-str digit-limit crash (infra, not ours)
]

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


def _find_any_row(class_name: str, task_id: str) -> dict | None:
    """First row for task_id across every perturbation file, regardless of split membership.

    Several of KNOWN_HARD_TASKS belong to the train split (confirmed against
    data/splits/{train,validation}.txt), so --source val's split-filtered _val_rows() can't
    find them -- this is the fallback used to force them in anyway.
    """
    for path in sorted(VARIANT_DIR[class_name].glob("*.jsonl")):
        for row in _load_rows(path):
            if row["task_id"] == task_id and row.get("prompt"):
                return row
    return None


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
    ap.add_argument(
        "--hard-tasks",
        default=",".join(KNOWN_HARD_TASKS),
        help="Comma-separated task_ids to force into the sample; '' disables (default: "
        "the known-hardest set, see module docstring)",
    )
    args = ap.parse_args()

    classes = [c.strip() for c in args.classes.split(",") if c.strip()]
    for c in classes:
        if c not in CANONICAL_FILE:
            raise ValueError(f"Unknown class `{c}`; known classes: {sorted(CANONICAL_FILE)}")

    hard_tasks = {t.strip() for t in args.hard_tasks.split(",") if t.strip()}

    rng = random.Random(args.seed)

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pass 1: gather each class's candidate rows and forced (hard-task) rows, so a class whose
    # universe is too small for an even split (e.g. --source val's HumanEval has only 30 distinct
    # task_ids) can have its shortfall picked up by a class with room, instead of just serving a
    # smaller total than --n asked for.
    per_class_data: dict[str, dict] = {}
    for class_name in classes:
        if args.source == "val":
            # preprocess_benchmark keys a file's tasks by task_id, so two variants of the same
            # task in one file would silently collapse into one: keep one random variant per id.
            rows = _val_rows(class_name)
            rng.shuffle(rows)
            rows = list({row["task_id"]: row for row in reversed(rows)}.values())
        else:
            rows = _load_rows(CANONICAL_FILE[class_name])

        class_hard_ids = {t for t in hard_tasks if t.split("/", 1)[0] == class_name}
        forced = [r for r in rows if r["task_id"] in class_hard_ids]
        found_ids = {r["task_id"] for r in forced}
        missing = []
        for tid in sorted(class_hard_ids - found_ids):
            fallback_row = _find_any_row(class_name, tid)
            if fallback_row is not None:
                forced.append(fallback_row)
            else:
                missing.append(tid)
        if missing:
            print(
                f"   {class_name}: hard task(s) not found anywhere, skipping: {missing}",
                file=sys.stderr,
            )
        forced_ids = {r["task_id"] for r in forced}
        rest = [r for r in rows if r["task_id"] not in forced_ids]
        per_class_data[class_name] = {
            "forced": forced,
            "rest": rest,
            "available": len(forced) + len(rest),
        }

    # Pass 2: split --n evenly across classes, then water-fill any shortfall (a class capped by
    # its own availability) into classes that still have room, so the total still reaches --n
    # whenever enough tasks exist somewhere.
    per_class, remainder = divmod(args.n, len(classes))
    quota = {
        c: min(per_class + (1 if i < remainder else 0), per_class_data[c]["available"])
        for i, c in enumerate(classes)
    }
    shortfall = args.n - sum(quota.values())
    while shortfall > 0:
        room = {
            c: per_class_data[c]["available"] - quota[c]
            for c in classes
            if quota[c] < per_class_data[c]["available"]
        }
        if not room:
            break  # no class has any room left; total will be short of --n
        for c in room:
            if shortfall == 0:
                break
            quota[c] += 1
            shortfall -= 1

    written_paths: list[str] = []
    for class_name in classes:
        forced = per_class_data[class_name]["forced"]
        rest = per_class_data[class_name]["rest"]
        k = max(quota[class_name], len(forced))  # never drop a forced task to fit the quota
        fill = min(max(k - len(forced), 0), len(rest))
        sample = forced + rng.sample(rest, fill)
        rng.shuffle(sample)

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
