#!/usr/bin/env python3
"""Injected statements: what a perturbed prompt says that its original does not.

Dev tooling (not part of the submission). For every variant of a run's results.jsonl, finds the
unperturbed prompt of the same task (`data/<class>/<class>_original.jsonl`) and the
perturbation file the variant comes from, splits both prompts into sentences and keeps the
variant's sentences that match no original sentence (difflib ratio below --threshold). These
are the statements the perturbation added or rewrote. The hidden tests check the original
behaviour, so code that obeys an injected statement the user never confirmed can fail.

Per variant it records the injected sentences and whether the clarification question was about
one of them (word overlap). Lexical-vagueness and syntax/formatting variants rewrite the whole
text, so for them almost every sentence counts as injected; the summary keeps them apart.

Usage:
  uv run python scripts/injected_statements.py results/runs/<run>/results.jsonl \
      [--out OUT.jsonl] [--threshold 0.6]
"""

from __future__ import annotations

import argparse
import collections
import difflib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = {"Mbpp": REPO_ROOT / "data" / "mbpp", "HumanEval": REPO_ROOT / "data" / "humaneval"}
REWRITES = ("lexical_vagueness", "syntax_and_formatting")  # whole-text rewrites
WORD = re.compile(r"[a-z0-9]+")
STOP = set("the a an of to and or is be in for that it its this with as by on are should".split())


def rows(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def sentences(prompt: str) -> list[str]:
    """Prose sentences of a prompt: no code lines, no doctest lines."""
    text = []
    for line in prompt.splitlines():
        stripped = line.strip().strip('"').strip("'").strip()
        if not stripped or re.match(r"(>>>|def |from |import |return |assert )", stripped):
            continue
        text.append(stripped)
    parts = re.split(r"(?<=[.!?])\s+|\n", " ".join(text))
    return [p.strip() for p in parts if len(WORD.findall(p.lower())) >= 4]


def words(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if w not in STOP}


def best_ratio(sentence: str, originals: list[str]) -> float:
    return max(
        (difflib.SequenceMatcher(None, sentence.lower(), o.lower()).ratio() for o in originals),
        default=0.0,
    )


def prose(prompt: str) -> list[str]:
    """Lowercase words of the prompt's prose and doctests, without the def line."""
    lines = [ln for ln in prompt.splitlines() if not re.match(r"\s*(def |from |import )", ln)]
    return WORD.findall(" ".join(lines).lower())


def word_diff(original: str, variant: str) -> tuple[list[str], list[str]]:
    """(inserted, deleted) runs of words, a typo of a deleted word not counted as inserted."""
    a, b = prose(original), prose(variant)
    inserted, deleted = [], []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        gone, new = a[i1:i2], b[j1:j2]
        if op in ("replace", "insert"):
            new = [
                w
                for w in new
                if not any(difflib.SequenceMatcher(None, w, g).ratio() >= 0.75 for g in gone)
            ]
            if [w for w in new if w not in STOP]:
                inserted.append(" ".join(new))
        if op in ("replace", "delete"):
            gone = [
                w
                for w in a[i1:i2]
                if not any(difflib.SequenceMatcher(None, w, n).ratio() >= 0.75 for n in b[j1:j2])
            ]
            if [w for w in gone if w not in STOP]:
                deleted.append(" ".join(gone))
    return inserted, deleted


def load_sources() -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Original prompt per task_id, and perturbation file per (task_id, prompt)."""
    original, source = {}, {}
    for cls, folder in DATA.items():
        for row in rows(folder / f"{cls.lower()}_original.jsonl"):
            original[row["task_id"]] = row["prompt"]
        for path in sorted(folder.glob("*.jsonl")):
            if path.stem.endswith("_original"):
                continue
            label = path.stem.split("_", 1)[1]
            for row in rows(path):
                if row.get("prompt"):
                    source.setdefault((row["task_id"], row["prompt"].strip()), label)
    return original, source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", help="results.jsonl of a run")
    parser.add_argument("--out", help="per-variant JSONL (failures only)")
    parser.add_argument("--threshold", type=float, default=0.6)
    args = parser.parse_args()

    original, source = load_sources()
    summary = collections.Counter()
    out = open(args.out, "w") if args.out else None
    for result in rows(Path(args.results)):
        key = (result["task_id"], result["prompt"].strip())
        label = source.get(key, "original" if key[1] == original.get(key[0], "").strip() else "?")
        family = "rewrite" if any(r in label for r in REWRITES) else "targeted"
        base = sentences(original.get(result["task_id"], ""))
        injected = [s for s in sentences(result["prompt"]) if best_ratio(s, base) < args.threshold]
        inserted, deleted = word_diff(original.get(result["task_id"], ""), result["prompt"])
        history = result.get("clarification_history") or []
        question = history[0][0] if history else ""
        asked = [s for s in injected if len(words(s) & words(question)) >= 3]
        status = "pass" if result["success"] else "fail"
        summary[(family, status, "injected" if injected else "clean")] += 1
        shape = (
            ("ins" if inserted else "")
            + ("+" if inserted and deleted else "")
            + ("del" if deleted else "")
        )
        summary[("words", status, shape or "typos only")] += 1
        if injected and not result["success"]:
            summary[
                (family, "fail", "injected, none asked" if not asked else "injected, asked")
            ] += 1
        if out and not result["success"]:
            record = {
                "task_id": result["task_id"],
                "label": label,
                "injected": injected,
                "inserted": inserted,
                "deleted": deleted,
                "asked_about": asked,
                "question": question,
                "answer": history[0][3] if history and len(history[0]) > 3 else "",
                "code": result.get("prompt_result", ""),
                "error": str(result.get("test_result", ""))[-400:],
            }
            out.write(json.dumps(record) + "\n")
    if out:
        out.close()
    for key in sorted(summary):
        print(" / ".join(key), summary[key])


if __name__ == "__main__":
    main()
