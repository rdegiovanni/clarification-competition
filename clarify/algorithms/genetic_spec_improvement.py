# SPDX-FileCopyrightText: 2026 Your Name <you@email.com>
#
# SPDX-License-Identifier: MIT

"""Genetic Specification Improvement.

The task description is the genome. A noisy LLM judge estimates the number of
issues in the current description. While it is judged faulty, one atomic
question is asked. The answer is turned into a single established fact and the
description is rewritten to state that fact, as if the original author had
written it (the mutation operator). Fitness is issues + LAMBDA * questions.
Code is generated only from the final description.

Team: Your Team Name
Team Members: Member 1
Main Contact: you@email.com
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from clarify.baselines.base import ClarificationAlgorithmBase
from clarify.env import ClarificationEnvironment, TooManyQuestionException

JUDGE_PROMPT = """You are judging whether a programming-task description is CORRECT.

A "programming-task description" specifies a coding problem: behavior, inputs/outputs,
constraints, and examples. Decide whether it is accurate, consistent, and internally
coherent.

Evaluate along:
1. Accuracy: Trace every given example against the stated rule. If any example's output
   contradicts the stated logic, the description is INCORRECT (this overrides everything).
2. Completeness: Is a constraint, filter, condition, edge-case rule or output type missing
   that would change which inputs qualify or how output is computed?
3. Consistency: Do examples, constraints and prose agree?
4. Clarity/Ambiguity: Would competent programmers following standard conventions
   (0-indexing, usual tie-breaking, natural reading of the task name) converge on the
   same behavior?

Key detection rules:
- Vague-placeholder red flag: phrases like "a certain type of X", "a certain number",
  "handles it in a standard way", "do something with", "some way" are INCORRECT
  (ambiguity or incompleteness) unless the details are given elsewhere.

Answer ONLY with a JSON object, no other text:
{"reasoning": "<max 80 words>", "verdict": "correct" | "incorrect",
"issue_type": "none" | "ambiguity" | "incompleteness" | "contradiction" | "correctness"}
Use issue_type "none" if and only if verdict is "correct".

TASK DESCRIPTION:
"""

QUESTION_PROMPT = """You help clarify a buggy programming-task description by asking the user ONE question.

Task description:
{spec}

Facts already established by the user:
{facts}

Judge findings (may be noisy):
{findings}

Previously asked (do not repeat):
{history}

Write ONE clarifying question that satisfies ALL of:
- Critical: it resolves a real blocker to a correct implementation.
- Not guessable: the answer cannot be reliably inferred by convention.
- Atomic: it targets exactly one requirement.
- Objective: it admits a single unambiguous answer. Where possible, give concrete
  alternatives or a concrete input with the output you would expect.
- No leakage: do not ask about implementation details, algorithms, or hidden tests.

If the description is already sufficient, return {{"question": null}}.
Answer ONLY with JSON: {{"question": "<text or null>"}}"""

EVOLVE_SYSTEM = """You maintain the text of a programming-task description. A user just answered a clarification
question. Rewrite the description so that it states the fact the answer establishes, as if the original author had
written it.

Rules:
- Keep everything the answer does not contradict: wording, examples, the function name. Keep the same format (if the
  description is a docstring, return a docstring).
- Add only what the answer states. No default readings, no examples you computed, no implementation hints, no
  guesses about what the answer leaves open.
- Put the fact in its natural place: a sentence for the criterion, the inputs or the return form. If the answer
  replaces an earlier statement, replace it; never keep two conflicting statements.
- A fact about a criterion is not a new argument. Add a parameter to the description only if the answer says that the
  caller supplies it.
- If the answer states the arguments, write "The function takes ..." with their number and kinds.
- If the answer is partial, evasive or states no fact, set changed to false and return the description unchanged.
- The description grows by at most two sentences per answer.

Reply with one ```json block:
{"changed": true, "fact": "the fact the answer establishes, one sentence, or null",
 "description": "the full rewritten description"}"""

IMPL_PROMPT = """Implement the Python function `{entry}` for the task below.
Use only the standard library. Return ONLY one ```python code block containing the
complete implementation (imports and the function). Do not ask questions.

{spec}"""


def _parse_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from a ```json block or from bare text."""
    block = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.S)
    candidates = [block.group(1)] if block else []
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return {}


def _llm_json(env, system: str, user: str, tries: int = 1) -> dict[str, Any]:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for _ in range(max(1, tries)):
        out = _parse_json(env.llm(msgs))
        if out:
            return out
    return {}


def _code(text: str) -> str | None:
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return blocks[-1].strip() if blocks else None


class GeneticSpecClarification(ClarificationAlgorithmBase):
    MAX_QUESTIONS = 3
    N_JUDGES = 3
    LAMBDA = 0.3  # fitness penalty per question
    ASK_THRESHOLD = 2  # min fitness issues before spending a question
    MAX_GROWTH = 1.6  # reject rewrites that bloat the description

    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        max_q = self.config.get("max_questions", self.MAX_QUESTIONS)
        self.env = env
        self.entry = problem["entry_point"]
        self.desc = problem["prompt"]
        self.facts: list[str] = []
        history: list[tuple[str, str]] = []
        wasted = 0

        issues, findings = self._issues(self.desc)
        while issues >= self.ASK_THRESHOLD and len(history) < max_q and env.can_ask():
            q = self._question(findings, history)
            if not q:
                break
            try:
                a = env.ask_human(q)
            except TooManyQuestionException:
                break
            history.append((q, a))

            if self._evolve(q, a):
                issues, findings = self._issues(self.desc)
                wasted = 0
            else:
                wasted += 1
                if wasted >= 2:  # the user keeps giving no usable fact
                    break

        return self._implement(self.desc, self.entry)

    # ---- fitness ------------------------------------------------------
    def _issues(self, spec: str) -> tuple[float, list[str]]:
        incorrect, types, notes = 0, set(), []
        for _ in range(self.N_JUDGES):
            r = _parse_json(self.env.llm(JUDGE_PROMPT + spec))
            if r.get("verdict") == "incorrect":
                incorrect += 1
                types.add(r.get("issue_type", "ambiguity"))
                notes.append(f"[{r.get('issue_type')}] {r.get('reasoning', '')}")
        return incorrect + 0.5 * len(types), notes

    # ---- mutation operator -------------------------------------------
    def _evolve(self, question: str, answer: str) -> bool:
        """Rewrite self.desc with the fact the answer establishes.

        Returns True if the description changed.
        """
        user = (
            f"CURRENT DESCRIPTION:\n{self.desc}\n\nENTRY POINT: {self.entry}\n\n"
            f"QUESTION: {question}\nANSWER: {answer}\n"
        )
        out = _llm_json(self.env, EVOLVE_SYSTEM, user, tries=1)
        new = out.get("description")
        if not out.get("changed") or not isinstance(new, str) or not new.strip():
            return False
        new = new.strip()
        if new == self.desc.strip():
            return False
        # Guards: keep the signature and bound the growth of the description.
        if f"def {self.entry}" in self.desc and f"def {self.entry}" not in new:
            return False
        if len(new) > self.MAX_GROWTH * len(self.desc) + 400:
            return False
        self.desc = new
        fact = out.get("fact")
        if isinstance(fact, str) and fact.strip():
            self.facts.append(fact.strip())
        return True

    # ---- question generation -----------------------------------------
    def _question(self, findings, history) -> str | None:
        hist = "\n".join(f"- {q}" for q, _ in history) or "(none)"
        facts = "\n".join(f"- {f}" for f in self.facts) or "(none)"
        fnd = "\n".join(findings[:3]) or "(none)"
        r = _parse_json(
            self.env.llm(
                QUESTION_PROMPT.format(
                    spec=self.desc, facts=facts, findings=fnd, history=hist
                )
            )
        )
        q = r.get("question")
        return q.strip() if isinstance(q, str) and q.strip() else None

    # ---- final code generation ---------------------------------------
    def _implement(self, spec: str, entry: str) -> str:
        msgs = [{"role": "user", "content": IMPL_PROMPT.format(entry=entry, spec=spec)}]
        code = None
        for _ in range(2):
            resp = self.env.llm(msgs)
            code = _code(resp)
            if code:
                try:
                    tree = ast.parse(code)
                    if any(
                        isinstance(n, ast.FunctionDef) and n.name == entry
                        for n in ast.walk(tree)
                    ):
                        break
                except SyntaxError:
                    pass
            msgs += [
                {"role": "assistant", "content": resp},
                {
                    "role": "user",
                    "content": f"Invalid. Return valid Python defining `{entry}` in one ```python block.",
                },
            ]
        return f"```python\n{code or ''}\n```"