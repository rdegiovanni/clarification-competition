#!/usr/bin/env python3
"""Pass rate per benchmark and the origin of every failure of one or more runs.

Dev tooling (not part of the submission). Reads each run's results.jsonl and classifies every
failed task from its test output:

  signature: extra args   the test passes more positional arguments than the code declares
  signature: missing args the test passes fewer
  signature: order/type   the first statement touching an argument fails on its type
                          ('int' object is not iterable, has no attribute, ...)
  no usable code          syntax/indentation error, entry point not defined, empty body
  wrong type              Expected/got values of different Python types ('Yes' vs True,
                          tuple vs list, '1' vs 1, ...)
  wrong value             same type, different value (or a bare failing assert)
  crash                   any other exception raised by the code
  timeout                 the sandbox timed out
  sandbox                 the harness itself failed (e.g. int-to-str digit limit)

For each class it also reports how many of those tasks asked a question and how many answers
were QUALITY=3, which separates "asked and still failed" from "never asked".

Usage:
  uv run python scripts/classify_failures.py results/runs/<run> [results/runs/<run> ...]
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import re
from pathlib import Path

SIGNATURE_COUNT = re.compile(r"takes (\d+) positional arguments? but (\d+) (?:were|was) given")
MISSING_ARGS = re.compile(r"missing \d+ required positional argument")
TYPE_ON_ARGS = re.compile(
    r"'(int|str|list|tuple|float|dict|set|NoneType|bool)' object (is not iterable|has no attribute"
    r"|is not subscriptable|cannot be interpreted)|unsupported operand type|can only concatenate"
    r"|not supported between instances|object of type '\w+' has no len"
)
NO_CODE = re.compile(
    r"SyntaxError|IndentationError|NameError: name '(\w+)' is not defined|no python code block"
)
# The message line, not the f-string source line the traceback also prints.
EXPECTED_GOT = re.compile(
    r"AssertionError: Failed for inputs .*?: Expected '(.*)', but got (.*?)\s*(?:```|\Z)", re.S
)
EXCEPTION = re.compile(r"^(\w+(?:Error|Exception))\b", re.M)


def kind(text: str) -> str:
    """The shape of a value as the harness prints it (str(), not repr(): 'Yes' and True
    both arrive as bare text)."""
    text = text.strip()
    if text in ("True", "False"):
        return "bool"
    if text == "None":
        return "None"
    try:
        value = ast.literal_eval(text)
    except Exception:
        return "text"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__  # list, tuple, dict, set, str (a quoted repr inside)


def classify(result: dict) -> str:
    out = result.get("test_result") or ""
    if "int max str digits" in out.lower() or "exceeds the limit (4300" in out:
        return "sandbox"
    if "timed out" in out.lower() or "TimeoutError" in out or "Timeout" in out:
        return "timeout"
    count = SIGNATURE_COUNT.search(out)
    if count:
        declared, given = int(count.group(1)), int(count.group(2))
        return "signature: extra args" if given > declared else "signature: missing args"
    if MISSING_ARGS.search(out):
        return "signature: missing args"
    if NO_CODE.search(out) or not (result.get("prompt_result") or "").strip():
        return "no usable code"
    if TYPE_ON_ARGS.search(out):
        return "signature: order/type"
    match = EXPECTED_GOT.search(out)
    if match:
        if kind(match.group(1)) != kind(match.group(2)):
            return "wrong type"
        return "wrong value"
    if "AssertionError" in out:
        return "wrong value"
    if EXCEPTION.search(out):
        return "crash"
    return "crash"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    args = parser.parse_args()
    for run in args.runs:
        rows = [json.loads(line) for line in (run / "results.jsonl").open()]
        print(f"== {run.name}: {sum(r['success'] for r in rows)}/{len(rows)} passed")
        for cls in ("Mbpp", "HumanEval"):
            sub = [r for r in rows if r["task_id"].startswith(cls)]
            if sub:
                passed = sum(r["success"] for r in sub)
                print(f"   {cls:9s} {passed}/{len(sub)} = {100 * passed / len(sub):.1f}%")
        failed = [r for r in rows if not r["success"]]
        groups: dict[str, list[dict]] = collections.defaultdict(list)
        for r in failed:
            groups[classify(r)].append(r)
        print(
            f"   {'origin':24s} {'fails':>5s} {'%fail':>6s} {'MBPP':>5s} {'HE':>4s} {'asked':>6s} {'Q=3':>4s}"
        )
        for name, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            mbpp = sum(r["task_id"].startswith("Mbpp") for r in rs)
            asked = [r for r in rs if r["clarification_history"]]
            good = sum(any(h[2] == "3" for h in r["clarification_history"]) for r in asked)
            print(
                f"   {name:24s} {len(rs):5d} {100 * len(rs) / max(len(failed), 1):5.1f}% "
                f"{mbpp:5d} {len(rs) - mbpp:4d} {len(asked):6d} {good:4d}"
            )


if __name__ == "__main__":
    main()
