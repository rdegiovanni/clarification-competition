#!/usr/bin/env python3
"""How often could the z3 layers of laaser_pinpoint_smt_3.py produce a question?

Dev tooling (not part of the submission). In the algorithm the solver layers run only when the
audit decides to code; here they run on every task of a run's smoke set, regardless of the
audit, to measure their ceiling:
  * find_certificate: a signature/example type clash, or a statement contradicting an example
    (z3);
  * find_interpretation_conflict: two readings of an audit defect returning different values
    on a concrete input (z3).
Each task gets one audit (the algorithm's own prompt) and the solver calls, through the same
LiteLLM model and temperature the benchmark uses. Results are joined with the run's pass/fail.

Usage:
  set -a && source .env && set +a
  uv run python scripts/measure_solver_coverage.py results/runs/<run> [--workers 8]
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from clarify.algorithms import laaser_pinpoint_smt_3 as smt
from clarify.llm import LanguageModel


class _Env:
    """Only what the solver layers use: llm()."""

    def __init__(self, model: str, temperature: float):
        self.model = LanguageModel(model, temperature=temperature)

    def llm(self, messages):
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        return self.model(messages)


def measure(env: _Env, problem: dict) -> dict:
    prompt, entry_point = problem["prompt"], problem["entry_point"]
    row = {"task_id": problem["task_id"]}
    examples = smt.extract_examples(prompt, entry_point)
    row["examples"] = len(examples)
    signature = smt.infer_signature(prompt, entry_point, examples) if examples else None
    row["type_clash"] = bool(signature and smt.type_clash(signature, entry_point))
    certificate = smt.find_certificate(env, problem)
    row["certificate"] = certificate["question"] if certificate else None
    rules = smt._rules(entry_point)
    audit = env.llm(
        smt._fill(
            smt.AUDIT_CHECKLIST_TEMPLATE,
            prompt=prompt,
            entry_point=entry_point,
            rules=rules,
            checklist=smt.checklist_block(prompt),
        )
    )
    question = smt.atomic_question(smt._parse_question(audit))
    row["audit_decision"] = smt._parse_decision(audit)
    row["audit_question"] = question
    row["defects"] = len(smt.audit_defects(audit))
    # Without the audit's question: the strongest ambiguity diverging on ordinary inputs (the
    # ceiling), then whether it is the same target the audit asked about (choose_ambiguity's
    # own overlap test).
    conflict = smt.find_interpretation_conflict(env, problem, audit, None)
    row["conflict"] = conflict["question"] if conflict else None
    row["conflict_same_target"] = bool(
        conflict
        and question
        and max(smt._overlap(question, conflict[key]) for key in ("quote", "A", "B")) >= 0.5
    )
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--model", default="openai/gpt-4.1-mini")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    problems = [
        json.loads(line)
        for path in sorted((args.run_dir / "smoke_data").glob("*.jsonl"))
        for line in path.open()
    ]
    passed = {
        r["task_id"]: r["success"] for r in map(json.loads, (args.run_dir / "results.jsonl").open())
    }
    env = _Env(args.model, args.temperature)
    with ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(lambda p: measure(env, p), problems))
    for row in rows:
        row["passed"] = passed.get(row["task_id"])

    out = args.run_dir / "solver_coverage.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def count(pred) -> str:
        hits = [r for r in rows if pred(r)]
        failed = sum(r["passed"] is False for r in hits)
        return f"{len(hits):3d} tasks ({failed} of them failed in the run)"

    print(f"tasks: {len(rows)}, cost ${env.model.total_cost:.4f}")
    print("with examples in the prompt     :", count(lambda r: r["examples"]))
    print("type clash (no LLM, no z3)      :", count(lambda r: r["type_clash"]))
    print("certificate (clash or z3 contr.):", count(lambda r: r["certificate"]))
    print("audit lists defects             :", count(lambda r: r["defects"]))
    print("interpretation conflict (z3)    :", count(lambda r: r["conflict"]))
    print("  ... same phrase as audit's q. :", count(lambda r: r["conflict_same_target"]))
    print("any solver question             :", count(lambda r: r["certificate"] or r["conflict"]))
    print(f"written: {out}")


if __name__ == "__main__":
    main()
