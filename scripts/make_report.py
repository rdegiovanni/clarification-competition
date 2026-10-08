#!/usr/bin/env python3
"""Builds a Markdown report for one scripts/evaluate.sh run and appends a row to results/history.csv.

Reuses the competition's own scoring code (evaluate_responses._compute_output_row and friends)
instead of re-deriving TDS/nDCG, so the numbers here always match what a real leaderboard
submission would compute.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluate_responses import _compute_output_row  # noqa: E402

HISTORY_PATH = REPO_ROOT / "results" / "history.csv"
LEADERBOARD_PATH = REPO_ROOT / "docs" / "data" / "leaderboard.csv"
HISTORY_FIELDS = [
    "timestamp",
    "commit",
    "dirty",
    "algorithm",
    "clarify_py",
    "model",
    "split",
    "dataset",
    "n_tasks",
    "tds",
    "ndcg",
    "pass_at_1",
    "clarification_rate",
    "over_asking_rate",
    "avg_cost_usd",
    "unittest_status",
    "run_dir",
]


def git_info() -> tuple[str, bool]:
    def run(cmd: list[str]) -> str:
        try:
            return subprocess.run(
                cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=True
            ).stdout.strip()
        except Exception:
            return "unknown"

    commit = run(["git", "rev-parse", "--short", "HEAD"])
    dirty = bool(run(["git", "status", "--porcelain"]))
    return commit, dirty


def load_jsonl(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def append_history_row(row: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    exists = HISTORY_PATH.exists()
    with HISTORY_PATH.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def breakdown_by_prefix(results: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in results:
        prefix = r["task_id"].split("/", 1)[0]
        groups.setdefault(prefix, []).append(r)

    out = []
    for prefix, items in groups.items():
        total = len(items)
        passed = sum(1 for r in items if r["success"])
        out.append({"group": prefix, "total": total, "passed": passed, "pass_rate": passed / total})

    return sorted(out, key=lambda g: g["pass_rate"])


def classify_failure(result: dict) -> str | None:
    if result["success"]:
        return None
    prompt_result = result.get("prompt_result") or ""
    test_result = (result.get("test_result") or "").lower()
    if "[exception]" in prompt_result.lower():
        return "exception raised inside the algorithm"
    if "timeout" in test_result:
        return "evalplus execution timeout"
    if "```python" not in prompt_result:
        return "no python code block returned"
    return "code ran but produced the wrong output"


def failure_breakdown(results: list[dict]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for r in results:
        reason = classify_failure(r)
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def fmt_pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def fmt4(x: float) -> str:
    return f"{x:.4f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--clarify-py", required=True)
    ap.add_argument("--results-path", required=True)
    ap.add_argument("--split", default="")
    ap.add_argument("--dataset-path", default="")
    ap.add_argument("--unittest-status", default="unknown")
    ap.add_argument("--unittest-log", default="")
    ap.add_argument("--temperature", default="")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    results = load_jsonl(args.results_path)
    official = _compute_output_row(results)
    n_tasks = len(results)

    commit, dirty = git_info()
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    split_field = args.split or "demo"
    if args.dataset_path:
        dataset_field = args.dataset_path
    elif args.split:
        dataset_field = f"split:{args.split}"
    else:
        dataset_field = "data/mbpp_demo_test.jsonl"

    history_row = {
        "timestamp": timestamp,
        "commit": commit,
        "dirty": "yes" if dirty else "no",
        "algorithm": official["algorithm"],
        "clarify_py": args.clarify_py,
        "model": official["model"],
        "split": split_field,
        "dataset": dataset_field,
        "n_tasks": n_tasks,
        "tds": fmt4(official["tds"]),
        "ndcg": fmt4(official["ndcg"]),
        "pass_at_1": fmt4(official["pass_at_1"]),
        "clarification_rate": fmt4(official["clarification_rate"]),
        "over_asking_rate": fmt4(official["over_asking_rate"]),
        "avg_cost_usd": f"{official['avg_cost_usd']:.6f}",
        "unittest_status": args.unittest_status,
        "run_dir": str(run_dir),
    }

    previous_rows = [
        r
        for r in read_csv_rows(HISTORY_PATH)
        if r["algorithm"] == history_row["algorithm"]
        and r["model"] == history_row["model"]
        and r["split"] == history_row["split"]
        and r["dataset"] == history_row["dataset"]
    ]
    previous_row = previous_rows[-1] if previous_rows else None

    append_history_row(history_row)

    leaderboard_rows = [r for r in read_csv_rows(LEADERBOARD_PATH) if r.get("track") == "main"]
    for r in leaderboard_rows:
        try:
            r["_tds"] = float(r["tds"])
        except (KeyError, ValueError):
            r["_tds"] = -1.0
    leaderboard_rows.sort(key=lambda r: -r["_tds"])

    groups = breakdown_by_prefix(results)
    failures = failure_breakdown(results)
    failing_ids = sorted(r["task_id"] for r in results if not r["success"])

    lines: list[str] = []
    lines.append(f"# Run report — {history_row['algorithm']} ({timestamp})")
    lines.append("")
    lines.append("## Metadata")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    for k, v in [
        ("Commit", f"`{commit}`" + (" (dirty — uncommitted changes)" if dirty else "")),
        ("Algorithm file", args.clarify_py),
        ("Model", official["model"]),
        ("Temperature", args.temperature or "0.7 (SDK default)"),
        (
            "Split / dataset",
            f"{split_field} ({dataset_field})" if split_field != "demo" else "demo (30 tasks)",
        ),
        ("Tasks evaluated", str(n_tasks)),
        ("Unit tests (tests/)", args.unittest_status),
    ]:
        lines.append(f"| {k} | {v} |")
    lines.append("")

    lines.append("## Unit tests")
    lines.append("")
    if args.unittest_status == "PASSED":
        lines.append(
            "All offline regression tests passed (`tests/`, no network/Docker — these catch "
            "exception-handling bugs that the live benchmark may not trigger)."
        )
    else:
        log_name = Path(args.unittest_log).name if args.unittest_log else "unittest.log"
        lines.append(
            f"**Unit tests did not pass** (`{args.unittest_status}`). See `{log_name}` in this "
            "run's folder before trusting the benchmark numbers below."
        )
    lines.append("")

    lines.append("## Official competition metrics")
    lines.append("")
    lines.append(
        "Computed with `evaluate_responses.py`'s own `_compute_output_row` / `_turn_discounted_sucess` "
        "/ `_normalized_discounted_cumulative_gain` — the same code a real leaderboard submission uses."
    )
    lines.append("")
    lines.append("| Metric | Value | Meaning |")
    lines.append("|---|---|---|")
    lines.append(
        f"| **TDS** (ranking metric) | {fmt4(official['tds'])} | turn-discounted success — higher is better |"
    )
    lines.append(
        f"| **nDCG** (tie-break) | {fmt4(official['ndcg'])} | clarification quality — higher is better |"
    )
    lines.append(f"| Pass@1 | {fmt_pct(official['pass_at_1'])} | raw pass rate |")
    lines.append(
        f"| Clarification rate | {fmt_pct(official['clarification_rate'])} | % tasks where ≥1 question was asked |"
    )
    lines.append(
        f"| Over-asking rate | {fmt_pct(official['over_asking_rate'])} | % well-specified tasks needlessly questioned |"
    )
    lines.append(
        f"| Avg. cost / task | ${official['avg_cost_usd']:.6f} | prompt cost only, reported, no rank effect |"
    )
    lines.append("")
    temp_value = args.temperature or "0.7"
    if temp_value != "0":
        lines.append(
            f"> Sampling temperature is {temp_value} (non-zero), so re-running on the exact same "
            "commit/dataset will still shift these numbers by a point or two — treat small deltas "
            "below as noise, not signal. Only trust a difference that holds up across more than one run."
        )
        lines.append("")

    if previous_row:
        lines.append("## Vs. previous run (same algorithm/model/split/dataset)")
        lines.append("")
        lines.append(f"Previous: commit `{previous_row['commit']}` at {previous_row['timestamp']}")
        lines.append("")
        lines.append("| Metric | Previous | Now | Δ |")
        lines.append("|---|---|---|---|")
        for key, label in [
            ("tds", "TDS"),
            ("ndcg", "nDCG"),
            ("pass_at_1", "Pass@1"),
            ("clarification_rate", "Clarification rate"),
            ("over_asking_rate", "Over-asking rate"),
        ]:
            prev_v = float(previous_row[key])
            now_v = float(history_row[key])
            delta = now_v - prev_v
            arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "=")
            lines.append(f"| {label} | {prev_v:.4f} | {now_v:.4f} | {arrow} {delta:+.4f} |")
        lines.append("")
    else:
        lines.append("## Vs. previous run")
        lines.append("")
        lines.append(
            "No earlier run recorded for this exact (algorithm, model, split, dataset) combination "
            "in `results/history.csv` — this is the first data point."
        )
        lines.append("")

    lines.append("## Public leaderboard position (informational only)")
    lines.append("")
    lines.append(
        "`docs/data/leaderboard.csv` rows were evaluated on `openai/gpt-4.1-mini`. "
        f"This run used `{official['model']}`, so ranking against it is **not an apples-to-apples "
        "comparison** — use it as a rough compass, not a verdict."
    )
    lines.append("")
    lines.append("| Rank | Algorithm | Team | Model | TDS |")
    lines.append("|---|---|---|---|---|")
    inserted = False
    rank = 0
    for row in leaderboard_rows:
        rank += 1
        if not inserted and official["tds"] >= row["_tds"]:
            lines.append(
                f"| → | **{official['algorithm']} (this run)** | us | {official['model']} | "
                f"**{fmt4(official['tds'])}** |"
            )
            inserted = True
        team = row.get("team") or (
            "baseline" if row.get("is_baseline", "").lower() == "true" else ""
        )
        lines.append(
            f"| {rank} | {row['algorithm']} | {team} | {row['model']} | {row['_tds']:.4f} |"
        )
    if not inserted:
        lines.append(
            f"| → | **{official['algorithm']} (this run)** | us | {official['model']} | "
            f"**{fmt4(official['tds'])}** |"
        )
    lines.append("")

    lines.append("## Breakdown by benchmark (lowest pass-rate first — fix these first)")
    lines.append("")
    lines.append("| Benchmark | Passed | Total | Pass rate |")
    lines.append("|---|---|---|---|")
    for g in groups:
        lines.append(f"| {g['group']} | {g['passed']} | {g['total']} | {fmt_pct(g['pass_rate'])} |")
    lines.append("")

    if failures:
        lines.append("## Failure reasons (priority order)")
        lines.append("")
        lines.append("| Reason | Count |")
        lines.append("|---|---|")
        for reason, count in failures:
            lines.append(f"| {reason} | {count} |")
        lines.append("")

    if failing_ids:
        lines.append("## Failing task IDs")
        lines.append("")
        lines.append(", ".join(failing_ids))
        lines.append("")

    lines.append("## Suggested next steps")
    lines.append("")
    suggestions = []
    if official["over_asking_rate"] > 0:
        suggestions.append(
            f"Over-asking rate is {fmt_pct(official['over_asking_rate'])} — the algorithm is "
            "questioning tasks that didn't need it, which directly costs TDS/nDCG vs. just answering."
        )
    if official["clarification_rate"] > 0:
        asked = [r for r in results if r["clarification_history"]]
        hq = sum(1 for r in asked if all(e[2] == "3" for e in r["clarification_history"]))
        if asked and hq / len(asked) < 0.7:
            suggestions.append(
                f"Only {fmt_pct(hq / len(asked))} of clarification questions were rated high-quality "
                "(score 3) — review question phrasing against the Criticality/Search-space/Leakage/"
                "Atomicity/Objectivity criteria in the README."
            )
    if len(groups) > 1 and groups[0]["pass_rate"] < groups[-1]["pass_rate"] - 0.15:
        suggestions.append(
            f"{groups[0]['group']} pass rate ({fmt_pct(groups[0]['pass_rate'])}) is notably weaker "
            f"than {groups[-1]['group']} ({fmt_pct(groups[-1]['pass_rate'])}) — look at "
            f"{groups[0]['group']} failures first."
        )
    if not suggestions:
        suggestions.append(
            "No obvious red flag from this single run; compare the TDS trend across multiple runs "
            "in `results/history.csv` before concluding anything changed."
        )
    for s in suggestions:
        lines.append(f"- {s}")
    lines.append("")

    report_text = "\n".join(lines)
    (run_dir / "report.md").write_text(report_text)
    (REPO_ROOT / "results" / "latest_report.md").write_text(report_text)

    print(f"Report written to {run_dir / 'report.md'}")
    print("Latest report: results/latest_report.md")
    print(
        f"TDS={fmt4(official['tds'])} nDCG={fmt4(official['ndcg'])} "
        f"Pass@1={fmt_pct(official['pass_at_1'])}"
    )


if __name__ == "__main__":
    main()
