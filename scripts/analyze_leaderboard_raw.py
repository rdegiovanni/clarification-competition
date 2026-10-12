#!/usr/bin/env python3
"""Splits val-split results by whether each task really needed clarification.

Reads the organizers' per-task leaderboard results (docs/data/raw/*_results.jsonl, all
openai/gpt-4.1-mini on the 770-task val split) plus any of our own val-split results.jsonl
files, and joins them with data/clarifications.jsonl, whose per-task hidden Q/A pairs are what
the simulated human answers from (an empty list = a clean task that needs no question).

For each algorithm it prints TDS, Pass@1 and ask rate, then the same numbers on clean vs.
needs-clarification tasks, pass rate when it asked vs. didn't ask on needs-clarification tasks,
and pass rate by number of hidden requirements. This is the table that shows where TDS is
actually won or lost on the real task mix -- something a smoke set drawn only from the
*_original.jsonl files cannot show, since none of its tasks carry hidden requirements.

Usage:
  uv run python scripts/analyze_leaderboard_raw.py \\
      [--ours LABEL=results/runs/<run>/results.jsonl ...]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "docs" / "data" / "raw"
CLARIFICATIONS = REPO_ROOT / "data" / "clarifications.jsonl"


def _load(path: Path) -> dict[tuple[str, str], dict]:
    with path.open() as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return {(r["task_id"], r["prompt"].strip()): r for r in rows}


def _rate(rows: list[dict], key) -> str:
    if not rows:
        return "   -  "
    return f"{sum(bool(key(r)) for r in rows) / len(rows):6.3f}"


def _passed(r: dict) -> bool:
    return bool(r["success"])


def _asked(r: dict) -> bool:
    return bool(r["clarification_history"])


def _tds(rows: list[dict]) -> float:
    gain = sum(
        math.log(10) / math.log(10 + len(r["clarification_history"])) for r in rows if r["success"]
    )
    return gain / len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", action="append", default=[], help="LABEL=path/to/results.jsonl")
    args = ap.parse_args()

    hidden: dict[tuple[str, str], int] = {}
    with CLARIFICATIONS.open() as f:
        for line in f:
            d = json.loads(line)
            hidden[(d["task_id"], d["prompt"].strip())] = len(d["clarifications"]) // 2

    sources = {p.name.removesuffix("_results.jsonl"): p for p in sorted(RAW_DIR.glob("*.jsonl"))}
    for spec in args.ours:
        label, path = spec.split("=", 1)
        sources[label] = Path(path)
    results = {label: _load(path) for label, path in sources.items()}

    keys = [k for k in hidden if all(k in r for r in results.values())]
    clean = [k for k in keys if hidden[k] == 0]
    need = [k for k in keys if hidden[k] > 0]
    print(f"{len(keys)} tasks in common: {len(clean)} clean, {len(need)} need clarification\n")

    print(
        f"{'algorithm':16s} {'TDS':>6s} {'pass':>6s} {'ask':>6s} | clean: {'pass':>6s} {'ask':>6s}"
        f" | need: {'pass':>6s} {'ask':>6s} | need, asked: {'pass':>6s} | need, no ask: {'pass':>6s}"
    )
    for label, res in results.items():
        rows = [res[k] for k in keys]
        c = [res[k] for k in clean]
        n = [res[k] for k in need]
        n_asked = [r for r in n if _asked(r)]
        n_silent = [r for r in n if not _asked(r)]
        print(
            f"{label:16s} {_tds(rows):6.3f} {_rate(rows, _passed)} {_rate(rows, _asked)} | "
            f"       {_rate(c, _passed)} {_rate(c, _asked)} | "
            f"      {_rate(n, _passed)} {_rate(n, _asked)} | "
            f"{_rate(n_asked, _passed)} (n={len(n_asked):3d}) | "
            f"{_rate(n_silent, _passed)} (n={len(n_silent):3d})"
        )

    print("\nPass rate by number of hidden requirements (4 = 4 or more):")
    buckets = sorted({min(hidden[k], 4) for k in keys})
    print(f"{'algorithm':16s} " + " ".join(f"{b:>12d}" for b in buckets))
    for label, res in results.items():
        cells = []
        for b in buckets:
            ks = [k for k in keys if min(hidden[k], 4) == b]
            ok = sum(res[k]["success"] for k in ks)
            cells.append(f"{ok:4d}/{len(ks):3d}={ok / len(ks):.2f}")
        print(f"{label:16s} " + " ".join(f"{c:>12s}" for c in cells))


if __name__ == "__main__":
    main()
