# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""LAASeR 2.0.

Second iteration of our submission, after measuring where LAASeRAlgorithm (v1)
actually loses points on `openai/gpt-4.1-mini`:

1. v1's loop re-sends the same combined "ready or ask" prompt after an answer
   comes back; on a model that doesn't reliably reuse the READY_TO_CODE/QUESTION
   keywords on a second turn, that silently returns an empty candidate. v2 asks
   at most once, with a dedicated yes/no "gate" step, then always moves on to a
   dedicated solve step -- there is no second decision point to fall through.
2. v1 only checked for a non-empty fenced block. That accepts code that parses
   out of the fence but defines the wrong function name or isn't valid Python at
   all -- both measured as a sizeable share of v1's "failures" on the full `val`
   split (see REPORT.md). v2 validates the parsed code with `ast` before
   accepting it: it must parse, and it must define a function literally named
   `entry_point`. If it doesn't, we ask the model to fix just that, instead of
   giving up.
3. v1 could return "" with nothing to submit. v2 always submits *something*
   syntactically valid and correctly named, even on total failure -- a stub that
   raises NotImplementedError still fails the hidden tests, but it can never be
   misreported as "no code returned" or crash the harness.

Team: LAASeR - LIST
Team Members: Matias Brizzio, Jordi Cabot, Renzo Degiovanni
Main Contact: main.contact@email.com
"""

from __future__ import annotations

import ast
from typing import Any

from clarify.baselines import ClarificationAlgorithmBase
from clarify.env import ClarificationEnvironment, LimitsExceededException, TooManyQuestionException
from clarify.runtime import _validate_and_parse_evalplus_result

GATE_TEMPLATE = """
Below is a coding task. Decide whether it is genuinely underspecified: is there
some fact about the required behaviour that you'd have to guess, such that
guessing wrong would make an otherwise-correct implementation fail the hidden
tests?

Task (function to implement: `{entry_point}`):
{prompt}

Ignore naming, style, or anything you can reasonably infer from the description
or the examples -- those don't justify a question. Only ask about a real
behavioural ambiguity.

If you have everything you need, reply with exactly:
NO_QUESTION

Otherwise reply with exactly one line:
QUESTION: <one specific question about exactly one missing fact>
""".strip()

SOLVE_TEMPLATE = """
Implement the function `{entry_point}` for the task below.
{clarification_block}
Task:
{prompt}

Reply with the complete implementation enclosed in ```python and ```. The
function must be named exactly `{entry_point}`.
""".strip()

CLARIFICATION_BLOCK_TEMPLATE = """
A clarifying question was already asked and answered -- follow the answer
exactly, even where it contradicts your own first reading of the task:
Q: {question}
A: {answer}
"""

REPAIR_TEMPLATE = """
That response wasn't usable: either it had no ```python ... ``` block, the code
inside didn't parse, or it didn't define a function named exactly
`{entry_point}`. Reply again with only the corrected implementation, enclosed
in ```python and ```, defining `{entry_point}`.
""".strip()

FALLBACK_SOLUTION_TEMPLATE = """```python
def {entry_point}(*args, **kwargs):
    raise NotImplementedError
```"""

MAX_REPAIR_ATTEMPTS = 2


def _is_usable_solution(response: str, entry_point: str) -> bool:
    try:
        code = _validate_and_parse_evalplus_result(response)
    except ValueError:
        return False

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_point
        for node in ast.walk(tree)
    )


def _parse_gate_verdict(verdict: str) -> str | None:
    lines = [line.strip() for line in verdict.splitlines() if line.strip()]

    for line in lines:
        bare = line.upper().strip("`*. ")
        if bare == "NO_QUESTION":
            return None
        if bare.startswith("QUESTION"):
            _, _, question = line.partition(":")
            question = question.strip()
            if question:
                return question

    # Unrecognisable verdict: if it reads like a single question, ask it rather
    # than silently treating a confused reply as "no question".
    if len(lines) == 1 and lines[0].endswith("?"):
        return lines[0]

    return None


class LAASeR2Algorithm(ClarificationAlgorithmBase):
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        entry_point = problem["entry_point"]
        prompt = problem["prompt"]
        clarification_block = ""

        if env.can_ask():
            try:
                verdict = env.llm(GATE_TEMPLATE.format(prompt=prompt, entry_point=entry_point))
                question = _parse_gate_verdict(verdict)
            except LimitsExceededException:
                question = None

            if question:
                try:
                    answer = env.ask_human(question)
                    clarification_block = CLARIFICATION_BLOCK_TEMPLATE.format(
                        question=question, answer=answer
                    )
                except TooManyQuestionException:
                    pass

        messages = [{
            "role": "user",
            "content": SOLVE_TEMPLATE.format(
                prompt=prompt, entry_point=entry_point, clarification_block=clarification_block
            ),
        }]

        for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
            try:
                response = env.llm(messages)
            except LimitsExceededException:
                break

            if _is_usable_solution(response, entry_point):
                return response

            if attempt == MAX_REPAIR_ATTEMPTS:
                break

            messages = messages + [
                {"role": "assistant", "content": response},
                {"role": "user", "content": REPAIR_TEMPLATE.format(entry_point=entry_point)},
            ]

        return FALLBACK_SOLUTION_TEMPLATE.format(entry_point=entry_point)
