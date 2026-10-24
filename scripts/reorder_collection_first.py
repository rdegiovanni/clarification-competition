#!/usr/bin/env python3
"""Offline what-if: reorder (scalar, collection) entry-point parameters to (collection, scalar).

Dev tooling (not part of the submission). Reads a run's generate.jsonl and, for every task whose
prompt does not show a `def` line, looks at the returned entry point: when it has exactly two
parameters and its body uses the first only as a scalar (arithmetic, comparisons, range()) and
the second as a collection (iterated, indexed, len(), sorted(), ...), the two are swapped in the
`def` line. The body refers to parameters by name, so nothing else changes. Writes a new
generation file for evaluate_responses.py, so the same code is scored with and without the
reorder -- no LLM call, no sampling noise.

In passing MBPP code from our runs, 31 of 33 such functions put the collection first; a coding
rule asking for it was ignored by the model (Mbpp/433 still coded as (number, arr)).

Usage:
  uv run python scripts/reorder_collection_first.py results/runs/<run>/generate.jsonl OUT.jsonl
"""

from __future__ import annotations

import argparse
import ast
import json
import re

COLLECTION_CALLS = {
    "len", "sorted", "set", "list", "sum", "max", "min", "enumerate", "zip", "reversed",
    "tuple", "dict", "any", "all", "map", "filter",
}  # fmt: skip


def roles(function: ast.FunctionDef) -> str:
    """'C' for a parameter used as a collection, 'S' for one used only as a scalar, '?'."""
    names = [a.arg for a in function.args.args]
    collection, scalar = set(), set()
    for node in ast.walk(function):
        if isinstance(node, (ast.For, ast.comprehension)) and isinstance(node.iter, ast.Name):
            collection.add(node.iter.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            first = node.args[0] if node.args else None
            if node.func.id in COLLECTION_CALLS and isinstance(first, ast.Name):
                collection.add(first.id)
            if node.func.id == "range":
                scalar.update(a.id for a in node.args if isinstance(a, ast.Name))
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            collection.add(node.value.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            collection.add(node.value.id)  # arr.append, s.split, d.items, ...
        elif isinstance(node, ast.BinOp):
            scalar.update(s.id for s in (node.left, node.right) if isinstance(s, ast.Name))
        elif isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            scalar.update(s.id for s in sides if isinstance(s, ast.Name))
    return "".join("C" if n in collection else ("S" if n in scalar else "?") for n in names)


def reorder(code: str, entry_point: str) -> str | None:
    """The code with the entry point's (scalar, collection) parameters swapped, or None."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == entry_point]
    if len(functions) != 1:
        return None
    function = functions[0]
    args = function.args
    if len(args.args) != 2 or args.defaults or args.vararg or args.kwonlyargs or args.kwarg:
        return None
    if roles(function) != "SC":
        return None
    first, second = args.args
    lines = code.splitlines(keepends=True)
    line = lines[function.lineno - 1]
    pattern = re.compile(
        rf"(def\s+{re.escape(entry_point)}\s*\(\s*)({re.escape(ast.unparse(first))})(\s*,\s*)"
        rf"({re.escape(ast.unparse(second))})(\s*\))"
    )
    swapped, count = pattern.subn(r"\1\4\3\2\5", line, count=1)
    if count != 1:
        return None
    lines[function.lineno - 1] = swapped
    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("generation", help="generate.jsonl of a run")
    parser.add_argument("output", help="new generation file")
    args = parser.parse_args()
    changed, total = [], 0
    with open(args.generation) as src, open(args.output, "w") as out:
        for line in src:
            row = json.loads(line)
            total += 1
            prompt, code = row.get("prompt", ""), row.get("prompt_result") or ""
            entry = None
            if not re.search(r"^\s*def\s+\w+\s*\(", prompt, re.M):
                names = re.findall(r"^def\s+(\w+)\s*\(", code, re.M)
                entry = names[-1] if names else None
            new = reorder(code, entry) if entry else None
            if new is not None:
                row["prompt_result"] = new
                changed.append(row["task_id"])
            out.write(json.dumps(row) + "\n")
    print(f"reordered {len(changed)} of {total}: {sorted(set(changed))}")


if __name__ == "__main__":
    main()
