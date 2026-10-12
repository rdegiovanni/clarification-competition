# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR Pinpoint algorithm.

Motivation (measured on the official val split, see scripts/analyze_leaderboard_raw.py): 75% of
val tasks carry hidden requirements, and those requirements sit exactly where the task text was
edited -- a contradiction, a vague phrase, a missing rule, or an out-of-place extra requirement.
Our earlier LAASeR variants asked on only ~30% of those tasks; when they did ask they passed as
often as the public leader (58%), and when they did not they passed only 39%. A single question
costs just ~4% of a task's TDS (log(10)/log(11) = 0.96), so on this distribution asking is cheap
and not asking is expensive.

Pinpoint therefore audits the task text first, localising each defect (with the exact phrase and
two competing readings, rated by whether they change outputs on ordinary inputs), and:
  * codes directly in the same call when no high-impact defect exists and the arguments and
    return format are fixed by the text (one LLM call, no question, full TDS credit);
  * otherwise asks ONE atomic, closed-form question about the defect that would break the most
    tests, quoting the phrase and offering the competing readings, then codes with the answer
    treated as authoritative.
The final candidate goes through a bounded syntax/entry-point repair step (no exec_code needed).

Team: LAASeR - LIST
Team Members: Matias Brizzio, Jordi Cabot, Renzo Degiovanni
Main Contact: main.contact@email.com
"""

from __future__ import annotations

import ast
import re
from typing import Any

from clarify.baselines import ClarificationAlgorithmBase
from clarify.env import ClarificationEnvironment, LimitsExceededException, TooManyQuestionException
from clarify.runtime import _validate_and_parse_evalplus_result

MAX_REPAIR_ATTEMPTS = 2
MIN_QUESTION_LENGTH = 10
MAX_QUESTION_LENGTH = 600

CODING_RULES = """
Rules for the implementation:
1. Name the function exactly `{entry_point}`, even if the task text uses another name. Keep the
   parameters shown in the task; if none are shown, use the most natural parameters for the
   description.
2. The hidden tests only compare return values. Never weaken or complicate the logic to satisfy
   requirements they cannot observe (time complexity, "no loops", "no recursion", style).
3. Where the task is still ambiguous or contradictory, choose the most standard, least surprising
   behaviour for a function with this name and purpose.
4. Write only the function (plus any imports and helpers it needs) in a single ```python block:
   no prints, no input(), no example usage.
""".strip()

AUDIT_TEMPLATE = """
You are about to implement a Python function for a user. The task text below may have been
edited so that it is vague, incomplete or self-contradictory. Hidden tests will call
`{entry_point}` and compare its return values with the behaviour the user really intends.
Before coding you may ask the user ONE clarifying question. A question is cheap, but
implementing the wrong behaviour fails the tests.

Task:
<<<
{prompt}
>>>

STEP 1 - DEFECTS. List every place where the task does not uniquely determine the values that
`{entry_point}` must return. Check in particular for:
- CONTRADICTION: two statements, or a statement and an example / signature / type hint, that
  cannot both hold.
- VAGUE: a word or phrase whose interpretation changes the output (e.g. "similar", "certain",
  "okay", "large", "standard").
- MISSING: something the code needs that the text never fixes: the arguments and their
  structure, the return type or format, a formula, a threshold, a tie-break rule, the result
  for a special input.
- ODD: an unusual extra requirement that looks out of place for this function.
Write one line per defect:
- <TYPE> | "<exact phrase from the task, or: not stated>" | reading A: ... | reading B: ... | IMPACT: HIGH or LOW
IMPACT is HIGH when the two readings return different values on ordinary inputs, and LOW when
they differ only on rare edge inputs. Requirements that tests cannot observe (time complexity,
"no loops", "no recursion", style, comments) are never defects. If there are none, write: - none

STEP 2 - DECISION.
If no defect is HIGH and the task (with its examples) fixes both the arguments and the exact
return format, write the line `DECISION: CODE` followed by the complete implementation.
Otherwise write the line `DECISION: ASK` followed by exactly one line:
QUESTION: <your question>
Ask about the HIGH defect that would make the most tests fail (contradictions and the return
format first, then missing rules and vague terms, edge cases last). Quote or name the phrase
and offer the competing readings, so that the complete answer is exactly one fact. Example:
QUESTION: The task says "a frequency similar to the value" - should the frequency be exactly equal to the value, or at least the value?
Ask about one thing only, and never ask for test cases or for the implementation.

{rules}
""".strip()

CODE_TEMPLATE = """
Implement the following Python task.

Task:
<<<
{prompt}
>>>
{clarification}
{rules}
""".strip()

CLARIFICATION_BLOCK = """
You asked the user a clarifying question. Their answer is authoritative: where it conflicts with
the task text, follow the answer.
Question: {question}
Answer: {answer}
"""

REPAIR_TEMPLATE = """
Your previous answer to the task below cannot be used: {problem}

Task:
<<<
{prompt}
>>>
{clarification}
Previous answer:
<<<
{response}
>>>

Return the corrected, complete implementation of `{entry_point}` in a single ```python block.
""".strip()

DECISION_PATTERN = re.compile(r"DECISION[\s:*`]*(ASK|CODE)", re.IGNORECASE)
QUESTION_PATTERN = re.compile(r"QUESTION\s*:\s*(.+)", re.IGNORECASE)
PLACEHOLDER_PATTERN = re.compile(r"\{(\w+)\}")


def _fill(template: str, **fields: str) -> str:
    # One pass over the template's own placeholders: the inserted values (task text, model or
    # user output) routinely contain literal braces and must never be substituted into.
    return PLACEHOLDER_PATTERN.sub(lambda m: fields.get(m.group(1), m.group(0)), template)


def _rules(entry_point: str) -> str:
    return _fill(CODING_RULES, entry_point=entry_point)


def _clarification_block(question: str | None, answer: str | None) -> str:
    if not question or not answer:
        return ""
    return _fill(CLARIFICATION_BLOCK, question=question, answer=answer)


def _parse_decision(response: str) -> str | None:
    match = DECISION_PATTERN.search(response)
    return match.group(1).upper() if match else None


def _parse_question(response: str) -> str | None:
    match = QUESTION_PATTERN.search(response)
    if not match:
        return None
    question = match.group(1).split("```", 1)[0].strip().strip("*`'\" ").strip()
    if len(question) < MIN_QUESTION_LENGTH:
        return None
    return question[:MAX_QUESTION_LENGTH]


def _check_code(response: str, entry_point: str) -> tuple[str | None, str | None]:
    """Returns (code, problem); problem is None when the code is usable as-is."""
    try:
        code = _validate_and_parse_evalplus_result(response)
    except ValueError:
        return None, "it does not contain a ```python code block."

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return code, f"the code is not valid Python ({e.msg}, line {e.lineno})."

    # Only module-level names count: the tests call the entry point at module scope.
    defined = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    defined |= {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    if entry_point not in defined:
        return code, f"it does not define a function named exactly `{entry_point}`."

    return code, None


def _alias_entry_point(code: str, entry_point: str) -> str | None:
    """Last resort when repairs fail: alias the only top-level function to the entry point."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    top_level = [
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if len(top_level) != 1:
        return None
    return f"{code.rstrip()}\n\n{entry_point} = {top_level[0]}\n"


def _finalize(
    env: ClarificationEnvironment,
    problem: dict[str, Any],
    response: str,
    clarification: str,
) -> str:
    """Validates the response, repairing it a bounded number of times; returns best code."""
    entry_point = problem["entry_point"]
    best = ""
    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        code, issue = _check_code(response, entry_point)
        if code is not None and issue is None:
            return code
        if code is not None and not best:
            best = code
        if attempt == MAX_REPAIR_ATTEMPTS:
            break
        response = env.llm(
            _fill(
                REPAIR_TEMPLATE,
                problem=issue,
                prompt=problem["prompt"],
                clarification=clarification,
                response=response,
                entry_point=entry_point,
            )
        )

    return _alias_entry_point(best, entry_point) or best


class LAASeR_Pinpoint(ClarificationAlgorithmBase):
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        prompt = problem["prompt"]
        entry_point = problem["entry_point"]
        rules = _rules(entry_point)
        candidate = ""

        try:
            audit = env.llm(
                _fill(AUDIT_TEMPLATE, prompt=prompt, entry_point=entry_point, rules=rules)
            )
            decision = _parse_decision(audit)
            question = _parse_question(audit)

            if decision == "CODE" or (decision is None and question is None):
                candidate = _check_code(audit, entry_point)[0] or ""
                return _finalize(env, problem, audit, "") or candidate

            answer = None
            if question and env.can_ask():
                try:
                    answer = env.ask_human(question)
                except TooManyQuestionException:
                    answer = None

            clarification = _clarification_block(question, answer)
            response = env.llm(
                _fill(CODE_TEMPLATE, prompt=prompt, clarification=clarification, rules=rules)
            )
            candidate = _check_code(response, entry_point)[0] or candidate
            candidate = _finalize(env, problem, response, clarification) or candidate
        except (TooManyQuestionException, LimitsExceededException):
            pass
        except Exception:
            # Never lose an already-usable candidate to an unexpected failure.
            pass

        return candidate
