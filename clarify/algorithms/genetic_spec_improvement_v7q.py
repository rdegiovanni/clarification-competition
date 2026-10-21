# SPDX-FileCopyrightText: 2026 Your Name <you@email.com>
#
# SPDX-License-Identifier: MIT

"""Genetic Specification Improvement with Nagini formalisation -- variant with v7's question rules.

Copy of genetic_spec_improvement.py (commit 9ebf797) with two changes, measured on smoke-70
(val, seed 42; docs/v7-failure-analysis.md):
- QUESTION_PROMPT follows the question rules of laaser_pinpoint_smt_3.py's audit (quoted phrase,
  competing readings, one fact, no test cases, no backticks): QUALITY=1 answers 12 -> 7.
- alias_entry_point: the returned code always defines the entry point (it sometimes came back
  as `def candidate`, failing every test with NameError).
Result: 41/70 (TDS 0.5675) vs. 43/70 for the original and 45-51 for v7.


1. The task description is the genome. A noisy LLM judge counts issues; while the
   description looks faulty, one atomic question is asked and the answer is used to
   rewrite the description (mutation).
2. (Optional) Formalisation: from the best description, infer pre/postconditions in
   the Nagini specification language (nagini_contracts). A question is asked only
   when the contract cannot be inferred. The contract is checked against the examples
   in the description and discarded if it contradicts them.
3. Implementation: code is generated from the description plus the contract (if any).
   The contract is guidance only; the returned code is plain standard-library Python.

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

QUESTION_PROMPT = """You help clarify a programming-task description by asking the user ONE question.
The description may have been edited so that it is vague, incomplete or self-contradictory;
hidden tests compare the function's return values with the behaviour the user really intends.

Task description:
{spec}

Facts already established by the user:
{facts}

Judge findings (may be noisy):
{findings}

Previously asked (do not repeat):
{history}

First, for yourself, list every place where the description does not uniquely determine the
return values: a CONTRADICTION (two statements, or a statement and an example / signature /
type hint, that cannot both hold), a VAGUE word whose interpretation changes the output, a
MISSING rule (the arguments and their structure, the return type or format, a formula, a
threshold, a tie-break, the result for a special input), or an ODD extra requirement. Each has
two readings; it matters when they return different values on ordinary inputs. Requirements
tests cannot observe (time complexity, "no loops", style) never matter.

Then ask about the place that would make the most tests fail (contradictions and the return
format first, then missing rules and vague terms, edge cases last). Quote or name the phrase
and offer the competing readings, so that the complete answer is exactly one fact. Example:
The task says "a frequency similar to the value" - should the frequency be exactly equal
to the value, or at least the value?
Ask about one thing only, never ask for test cases, expected outputs or the implementation, and
do not use backticks.

If no place matters, return {{"question": null}}.
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

FORMALISE_SYSTEM = """You write Nagini contracts (the nagini_contracts specification language, used by the Nagini
verifier for statically typed Python 3) for ONE Python function, from its task description.

Nagini conventions:
- First line: `from nagini_contracts.contracts import *` (plus `from typing import List, Dict, Set, Optional, ...`).
- The function needs full type annotations. Use the signature from the description when it is given; otherwise
  derive types ONLY from what the description states.
- Preconditions: `Requires(<bool expr>)`. Postconditions: `Ensures(<bool expr>)`. Both are calls at the top of the
  function body, before any other statement.
- `Result()` is the return value. `Old(e)` is the value of e in the pre-state.
- Quantifiers: `Forall(range(len(xs)), lambda i: Implies(cond, body))`, `Exists(...)`, `Forall(int, lambda i: ...)`.
  Also `Implies(a, b)`.
- Mutable containers need permissions: `Acc(list_pred(xs))`, `Acc(dict_pred(d))`, `Acc(set_pred(s))` in both Requires
  and Ensures when the function reads them. Immutable values (int, bool, str, tuple) need none.
- Pure functions: `@Pure` decorator; use it when the function has no side effects and returns a value. For
  `@Pure` functions, do not use `Acc(...)` for the arguments you only read through `Requires`/`Ensures` when
  contract on the immutable type is enough.
- Exceptions: `Exsures(ValueError, <cond>)` only if the description says an exception is raised.
- The body must be just `...` (no implementation).

Rules:
- Encode ONLY what the description states or what its examples demonstrate. Do not invent constraints, defaults or
  tie-breaking rules. A weaker but true contract is better than a stronger guessed one.
- Every example in the description must satisfy the preconditions and the postconditions.
- Postconditions describe WHAT holds for the result, not HOW to compute it. No algorithms, no hidden-test guesses.
- If the contract cannot be inferred because one specific fact is missing (for example the return form, the handling
  of an invalid input, or which of two readings applies), do not guess: return status "need_clarification" with ONE
  atomic, objective question. Ask only if no sound contract exists without that fact. If a weaker sound contract
  exists, return it and list the open points under "assumptions".

Reply with one ```json block:
{"status": "ok" | "need_clarification",
 "contract": "complete Python source of the annotated function stub with Requires/Ensures, or null",
 "question": "one question, or null",
 "assumptions": ["short list of points left open, may be empty"]}"""

CONTRACT_CHECK_SYSTEM = """You check a Nagini contract against a task description.
For every input/output example in the description, decide whether the preconditions hold on the input and the
postconditions hold on the output. Also check the contract states nothing that the description contradicts.
Reply with one ```json block:
{"consistent": true | false, "reason": "max 40 words"}"""

IMPL_PROMPT = """Implement the Python function `{entry}` for the task below.
Use only the standard library. Return ONLY one ```python code block containing the
complete implementation (imports and the function). Do not ask questions.

{spec}"""

IMPL_WITH_CONTRACT_PROMPT = """Implement the Python function `{entry}` for the task below.
Use only the standard library. Return ONLY one ```python code block containing the
complete implementation (imports and the function). Do not ask questions.

Task description:
{spec}

A formal contract in the Nagini specification language was inferred from the description:
```python
{contract}
Make the implementation satisfy it: accept every input allowed by the Requires clauses and
return a result for which every Ensures clause holds. Treat the contract as a precise
restatement of the description; if the two ever differ, the description wins.
Do NOT import nagini_contracts and do NOT include Requires/Ensures/Old/Result/Acc calls in
your code: the answer must run with the plain Python standard library. Keep the function
name and argument order from the description."""

def _parse_json(text: Any) -> dict[str, Any]:
    """Extract a JSON object from a ```json block or from bare text. Always returns a dict."""
    # text = _as_text(text)
    candidates: list[str] = []
    for block in re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.S):
        candidates.append(block)
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return {}

def _llm_json(env, system: str, user: str, tries: int = 1) -> dict[str, Any]:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for _ in range(max(1, tries)):
        out = _parse_json(env.llm(msgs))
        if out:
            return out
    return {}

def _code(text):
    text = text or ""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    return blocks[-1].strip() if blocks else None

_CONTRACT_CALLS = {"Requires", "Ensures", "Exsures", "Invariant", "Decreases"}

def _contract_ok(src: str, entry: str) -> bool:
    """Cheap structural validation of a generated Nagini contract (no verifier call)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    fn = next(
    (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == entry),
    None,
    )
    if fn is None:
        return False
    calls = [
    s.value.func.id
    for s in fn.body
    if isinstance(s, ast.Expr)
    and isinstance(s.value, ast.Call)
    and isinstance(s.value.func, ast.Name)
    ]
    # At least one Requires/Ensures, all contract statements precede other statements.
    if not any(c in {"Requires", "Ensures", "Exsures"} for c in calls):
        return False
    seen_other = False
    for s in fn.body:
        is_contract = (
        isinstance(s, ast.Expr)
        and isinstance(s.value, ast.Call)
        and isinstance(s.value.func, ast.Name)
        and s.value.func.id in _CONTRACT_CALLS
        )
        is_doc = (
        isinstance(s, ast.Expr)
        and isinstance(s.value, ast.Constant)
        and isinstance(s.value.value, str)
        )
        if is_contract:
            if seen_other:
                return False
            elif not is_doc:
                seen_other = True
    return True

def alias_entry_point(code: str, entry: str) -> str:
    """The code, plus `entry = <name>` when it defines no top-level function called `entry`.

    The evolved description can stop naming the function ("candidate is a function that
    sums numbers"), and the model then names it freely: HumanEval/60 came back as
    `def candidate(n)` and failed every test with NameError. The alias keeps recursion and
    helper calls working. The last top-level function is taken (helpers usually come first).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code
    names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not names or entry in names:
        return code
    return f"{code.rstrip()}\n\n\n{entry} = {names[-1]}\n"


class GeneticSpecClarificationV7Q(ClarificationAlgorithmBase):
    MAX_QUESTIONS = 15
    N_JUDGES = 2
    LAMBDA = 0.3
    ASK_THRESHOLD = 1
    MAX_GROWTH = 1.6
    FORMALISE = True # optional step; override with config {"formalise": False}
    MAX_FORMAL_QUESTIONS = 1 # clarification budget for the formalisation step
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        self.config_max_q = self.config.get("max_questions", self.MAX_QUESTIONS)
        self.env = env
        self.entry = problem["entry_point"]
        self.desc = problem["prompt"]
        self.facts: list[str] = []
        self.history: list[tuple[str, str]] = []
        self.contract: str | None = None
        wasted = 0

        # ---- Phase 1: evolve the description -------------------------
        issues, findings = self._issues(self.desc)
        while (
            issues >= self.ASK_THRESHOLD
            and len(self.history) < self.config_max_q
            and env.can_ask()
        ):
            q = self._question(findings)
            if not q:
                break
            a = self._ask(q)
            if a is None:
                break
            if self._evolve(q, a):
                issues, findings = self._issues(self.desc)
                wasted = 0
            else:
                wasted += 1
                if wasted >= 2:
                    break

        # ---- Phase 2: optional formalisation -------------------------
        if self.config.get("formalise", self.FORMALISE):
            self.contract = self._formalise()

        # ---- Phase 3: implementation ---------------------------------
        return self._implement(self.desc, self.entry, self.contract)

    # ---- environment helper -------------------------------------------
    def _ask(self, q: str) -> str | None:
        try:
            a = self.env.ask_human(q)
        except TooManyQuestionException:
            return None
        self.history.append((q, a))
        return a

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
    def _question(self, findings) -> str | None:
        hist = "\n".join(f"- {q}" for q, _ in self.history) or "(none)"
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

    # ---- formalisation (Nagini pre/postconditions) --------------------
    def _formalise(self) -> str | None:
        """Infer a Nagini contract; ask the user only if none can be inferred.

        Returns the contract source, or None if formalisation failed or was
        rejected (the pipeline then falls back to the description alone).
        """
        formal_questions = 0
        while True:
            hist = "\n".join(f"- Q: {q} A: {a}" for q, a in self.history) or "(none)"
            user = (
                f"TASK DESCRIPTION:\n{self.desc}\n\nENTRY POINT: {self.entry}\n\n"
                f"CLARIFICATIONS ALREADY OBTAINED:\n{hist}\n"
            )
            out = _llm_json(self.env, FORMALISE_SYSTEM, user, tries=2)
            status = out.get("status")

            if status == "need_clarification":
                q = out.get("question")
                if (
                    not isinstance(q, str)
                    or not q.strip()
                    or formal_questions >= self.MAX_FORMAL_QUESTIONS
                    or len(self.history) >= self.config_max_q
                    or not self.env.can_ask()
                ):
                    return None  # impossible to infer, cannot ask: skip formalisation
                formal_questions += 1
                a = self._ask(q.strip())
                if a is None:
                    return None
                if not self._evolve(q.strip(), a):
                    return None  # unusable answer: do not formalise on guesses
                continue

            contract = out.get("contract")
            if status != "ok" or not isinstance(contract, str):
                return None
            contract = _code(contract) or contract.strip()
            if not _contract_ok(contract, self.entry):
                return None
            return contract if self._contract_consistent(contract) else None

    def _contract_consistent(self, contract: str) -> bool:
        """Reject contracts that contradict the examples/description."""
        user = f"TASK DESCRIPTION:\n{self.desc}\n\nCONTRACT:\n{contract}\n"
        out = _llm_json(self.env, CONTRACT_CHECK_SYSTEM, user, tries=1)
        return out.get("consistent") is True

    # ---- final code generation ---------------------------------------
    def _implement(self, spec: str, entry: str, contract: str | None) -> str:
        if contract:
            prompt = IMPL_WITH_CONTRACT_PROMPT.format(entry=entry, spec=spec, contract=contract)
        else:
            prompt = IMPL_PROMPT.format(entry=entry, spec=spec)

        resp = self.env.llm([{"role": "user", "content": prompt}])
        code = alias_entry_point(_code(resp) or str(resp or "").strip(), entry)
        return f"```python\n{code}\n```"