#!/usr/bin/env python3
"""Classify failures from one or more results.jsonl files into a detailed root-cause
taxonomy, so we can prioritize which failure class to attack next instead of guessing.

Dev tooling (not part of the submission). Reads already-computed results.jsonl files
under results/runs/ -- does not call env.llm/env.exec_code itself, just inspects the
`test_result` / `prompt_result` / `clarification_history` fields evaluate_responses.py
already wrote.

Usage:
    uv run python scripts/analyze_failures.py results/runs/<run>/results.jsonl [more...]
    uv run python scripts/analyze_failures.py "results/runs/*gatev2-s42*/results.jsonl"
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from collections import Counter, defaultdict

INFRA_DIGIT_LIMIT = "infra: sandbox int-to-str digit limit (organizer-owned, not fixable by us)"
NO_CODE = "no code returned (empty candidate)"
TIMEOUT = "evalplus execution timeout"
SIGNATURE_MISMATCH = "signature/arity mismatch (TypeError: wrong argument count)"
ENTRY_POINT_MISMATCH = "entry-point name mismatch (NameError)"
WRONG_OUTPUT = "code ran, wrong output (no exception)"

_SIGNATURE_RE = re.compile(
    r"typeerror.*(positional argument|missing \d+ required|takes \d+)", re.IGNORECASE
)
_EXC_NAME_RE = re.compile(r"\b([A-Za-z]+Error)\b")


def classify(result: dict) -> str:
    if result.get("success"):
        return "PASSED"

    task_id = result.get("task_id", "")
    prompt_result = result.get("prompt_result") or ""
    test_result = result.get("test_result") or ""
    test_result_lower = test_result.lower()

    if "exceeds the limit" in test_result_lower or task_id == "HumanEval/139":
        return INFRA_DIGIT_LIMIT
    if "timeout" in test_result_lower:
        return TIMEOUT
    if not prompt_result.strip():
        return NO_CODE
    if _SIGNATURE_RE.search(test_result):
        return SIGNATURE_MISMATCH
    if "nameerror" in test_result_lower:
        return ENTRY_POINT_MISMATCH
    if "assertionerror" in test_result_lower:
        return WRONG_OUTPUT

    exc_match = _EXC_NAME_RE.search(test_result)
    if exc_match:
        return f"runtime error: {exc_match.group(1)}"

    return WRONG_OUTPUT


def load_rows(paths: list[str]) -> list[dict]:
    rows = []
    for pattern in paths:
        for path in sorted(glob.glob(pattern)) or [pattern]:
            try:
                with open(path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            rows.append(json.loads(line))
            except FileNotFoundError:
                print(f"!! not found, skipping: {path}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="results.jsonl file(s) or glob pattern(s)")
    parser.add_argument(
        "--group-by",
        default="algorithm",
        choices=["algorithm", "none"],
        help="Group the breakdown by this result field (default: algorithm)",
    )
    args = parser.parse_args()

    rows = load_rows(args.paths)
    if not rows:
        print("No rows loaded.")
        return

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        key = r.get(args.group_by, "all") if args.group_by != "none" else "all"
        groups[key].append(r)

    overall_counts: Counter = Counter()
    overall_asked: Counter = Counter()
    overall_task_ids: dict[str, set] = defaultdict(set)

    for group_name, group_rows in sorted(groups.items()):
        print(f"\n=== {group_name} ({len(group_rows)} rows) ===")
        counts: Counter = Counter()
        asked_counts: Counter = Counter()
        tasks_by_category: dict[str, list[str]] = defaultdict(list)

        for r in group_rows:
            category = classify(r)
            counts[category] += 1
            overall_counts[category] += 1
            if category != "PASSED":
                asked = len(r.get("clarification_history", [])) > 0
                asked_counts[category] += 1 if asked else 0
                overall_asked[category] += 1 if asked else 0
                tasks_by_category[category].append(r.get("task_id", "?"))
                overall_task_ids[category].add(r.get("task_id", "?"))

        total = len(group_rows)
        passed = counts.get("PASSED", 0)
        print(f"  pass rate: {passed}/{total} ({100 * passed / total:.1f}%)")
        for category, n in counts.most_common():
            if category == "PASSED":
                continue
            n_asked = asked_counts[category]
            print(f"  {n:3d}  {category}  (asked a question: {n_asked}/{n})")
            print(f"       tasks: {', '.join(sorted(tasks_by_category[category]))}")

    if len(groups) > 1:
        print(f"\n=== TOTAL across {len(groups)} groups ===")
        total = sum(overall_counts.values())
        passed = overall_counts.get("PASSED", 0)
        print(f"  pass rate: {passed}/{total} ({100 * passed / total:.1f}%)")
        for category, n in overall_counts.most_common():
            if category == "PASSED":
                continue
            n_asked = overall_asked[category]
            n_unique_tasks = len(overall_task_ids[category])
            print(
                f"  {n:3d}  {category}  (asked a question: {n_asked}/{n}, "
                f"{n_unique_tasks} unique tasks)"
            )


if __name__ == "__main__":
    main()
