# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR with a draft-first, self-audited gate.

Fase 3 challenger #5 (first structural pivot after four consecutive wording-tweak
challengers failed to beat the champion LAASeR_Repair). Splits the champion's single
"decide to ask or code" call into two calls:

1. DRAFT: the model writes its best candidate directly, together with a short
   self-reported ASSUMPTIONS section listing anything it had to infer that the task
   text does not state explicitly (parameter list/signature, edge cases, defaults).
2. GATE: a second call is shown the draft plus its own listed assumptions and must
   pick at most one assumption that would actually change correctness if wrong; if
   none would, it says DONE, otherwise it asks exactly one atomic, concrete,
   closed-form question about a single input -- never an abstract definitional
   question, never more than one sub-question.

This targets two concrete, previously-observed failures: (a) questions that bundle
more than one sub-ask and come back with a vague, confidently-wrong answer, and
(b) signature/arity assumptions that a generic "don't assume the parameter list"
warning (tried in laaser_signature.py) failed to ever surface. Reuses the champion's
format/entry-point/parsing-error repair handlers unchanged -- those aren't part of
this hypothesis.

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

# generation codes
CODE_GEN = "CODE_GEN"
FORMAT_ERROR = "IncorrectOutputFormat"
PARSING_ERROR = "SyntaxError"
PARSING_OK = "CorrectSyntax"
INVALID_ENTRYPOINT = "InvalidEntryPoint"
GATE = "GATE"

# answer codes
READY_TO_CODE_KEY = "READY_TO_CODE"
QUESTION_KEY = "QUESTION"
DONE_KEY = "DONE"

MAX_DRAFT_ATTEMPTS = 8

DRAFT_TEMPLATE = """
Please find below a coding task.
Task:
`{prompt}`

Important: the function must be named exactly `{entry_point}` independently of the task text above.

First, write a short "ASSUMPTIONS:" section (plain bullet points) listing anything you had to
infer that is NOT explicitly stated in the task text above -- in particular: the exact parameter
list/signature if no function stub is shown, any edge case, sign, range, or type you assumed, and
any default or tie-break behavior you chose. If there is truly nothing you had to infer, write
"ASSUMPTIONS: none".

Then write READY_TO_CODE followed by ```python and ``` containing your best implementation.

Notice that you will be participating in a prompt clarification competition, where the goal is to
implement the correct python function, but unnecessary clarification turns are penalized -- so
write your best candidate directly here. You will get a separate chance to ask a question only if
one of your own listed assumptions turns out to be genuinely critical.
""".strip()

GATE_TEMPLATE = """
You drafted the candidate implementation below for a coding task, along with a list of
assumptions you made because the task text did not state them explicitly.

Candidate:
```python
{candidate}
```

Your stated assumptions:
`{assumptions}`

Pick AT MOST ONE assumption above that, if it turned out to be wrong, would most likely make this
candidate fail. If none of your assumptions would change whether the candidate is correct, or you
listed no assumptions, write DONE.

Otherwise, write QUESTION: followed by exactly ONE atomic, concrete, closed-form question that
confirms or denies a SINGLE specific fact about a SINGLE specific input -- for example a yes/no
question about what one concrete call should return, or a question about the exact name/count of
parameters for one specific case. Do not ask more than one thing, do not ask an abstract or
open-ended "what should happen" question, and do not ask the user to write code or reveal test
cases.
""".strip()

REPAIR_FORMAT_ERROR_TEMPLATE = """
For the given coding task, you generated a response that does not follow the expected output format.
Please fix it.

Response:
`{response}`

The expected format must enclose the response in ```python and ```
""".strip()

REPAIR_INVALID_ENDPOINT_TEMPLATE = """
You generated a response using an invalid function name (entry_point).
Please fix it.

Response:
`{response}`

entry_point:
The function must be named exactly `{entry_point}`.
""".strip()

REPAIR_PARSING_ERROR_TEMPLATE = """
You generated a response that is not python syntax correct and thus the parsing failed.
Please fix it.

Task:
`{prompt}`

Response:
`{response}`

entry_point:
The function must be named exactly `{entry_point}`.

Output Format:
The response must be enclosed in ```python and ```
""".strip()


def _draft(
    env: ClarificationEnvironment, problem: dict[str, Any], clarifications: list[str]
) -> str:
    gen_prompt = problem["prompt"]
    entry_point = problem["entry_point"]
    if len(clarifications) > 0:
        gen_prompt += "\n\nClarifications:\n"
        for c in clarifications:
            gen_prompt += c

    messages = [
        {
            "role": "user",
            "content": (
                DRAFT_TEMPLATE.replace("{prompt}", gen_prompt).replace("{entry_point}", entry_point)
            ),
        }
    ]

    return env.llm(messages)


def _gate(env: ClarificationEnvironment, candidate: str, assumptions: str) -> str:
    messages = [
        {
            "role": "user",
            "content": (
                GATE_TEMPLATE.replace("{candidate}", candidate).replace(
                    "{assumptions}", assumptions or "none"
                )
            ),
        }
    ]

    return env.llm(messages)


def _repair_format_error(env: ClarificationEnvironment, response: str) -> str:
    messages = [
        {
            "role": "user",
            "content": (REPAIR_FORMAT_ERROR_TEMPLATE.replace("{response}", response)),
        }
    ]

    return READY_TO_CODE_KEY + "\n" + env.llm(messages)


def _repair_invalid_entrypoint(
    env: ClarificationEnvironment, problem: dict[str, Any], response: str
) -> str:
    entry_point = problem["entry_point"]
    messages = [
        {
            "role": "user",
            "content": (
                REPAIR_INVALID_ENDPOINT_TEMPLATE.replace("{entry_point}", entry_point).replace(
                    "{response}", response
                )
            ),
        }
    ]

    return READY_TO_CODE_KEY + "\n" + env.llm(messages)


def _repair_parsing_error(
    env: ClarificationEnvironment, problem: dict[str, Any], clarifications: list[str], response: str
) -> str:
    gen_prompt = problem["prompt"]
    entry_point = problem["entry_point"]
    if len(clarifications) > 0:
        gen_prompt += "\n\nClarifications:\n"
        for c in clarifications:
            gen_prompt += c

    messages = [
        {
            "role": "user",
            "content": (
                REPAIR_PARSING_ERROR_TEMPLATE.replace("{prompt}", gen_prompt)
                .replace("{entry_point}", entry_point)
                .replace("{response}", response)
            ),
        }
    ]

    return READY_TO_CODE_KEY + "\n" + env.llm(messages)


def _parse_draft(response: str, entry_point: str) -> tuple[str, Any]:
    try:
        code = _validate_and_parse_evalplus_result(response)
    except ValueError as e:
        return FORMAT_ERROR, str(e)

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return PARSING_ERROR, str(e)

    if not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_point
        for node in ast.walk(tree)
    ):
        return INVALID_ENTRYPOINT, code

    assumptions = response.split("```python", 1)[0].replace(READY_TO_CODE_KEY, "").strip()
    return PARSING_OK, (code, assumptions)


class LAASeR_Gate(ClarificationAlgorithmBase):
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        clarifications: list[str] = []
        candidate = ""
        assumptions = ""
        try:
            entry_point = problem["entry_point"]
            status = CODE_GEN
            response = ""
            draft_attempts = 0
            while True:
                if status == GATE:
                    gate_response = _gate(env, candidate, assumptions)
                    if QUESTION_KEY in gate_response:
                        _, clarifying_question = gate_response.split(QUESTION_KEY, 1)
                        clarifying_question = (
                            clarifying_question[1:]
                            if clarifying_question.startswith(":")
                            else clarifying_question
                        )
                        clarification = env.ask_human(clarifying_question)
                        num_rounds = len(clarifications)
                        clarifications += [
                            f"Question #{num_rounds + 1}:\n{clarifying_question}\nAnswer:\n{clarification}\n"
                        ]
                        status = CODE_GEN
                        continue
                    else:  # DONE, or any malformed/non-question response: finish safely
                        return candidate

                if draft_attempts >= MAX_DRAFT_ATTEMPTS:
                    return candidate
                draft_attempts += 1

                if status == CODE_GEN:
                    response = _draft(env, problem, clarifications)
                elif status == FORMAT_ERROR:
                    response = _repair_format_error(env, response)
                elif status == INVALID_ENTRYPOINT:
                    response = _repair_invalid_entrypoint(env, problem, response)
                else:  # PARSING_ERROR
                    response = _repair_parsing_error(env, problem, clarifications, response)

                if READY_TO_CODE_KEY in response:
                    new_status, payload = _parse_draft(response, entry_point)
                    if new_status == PARSING_OK:
                        candidate, assumptions = payload
                        status = GATE
                    else:
                        status = new_status
                else:
                    status = FORMAT_ERROR

        except TooManyQuestionException:
            print("---> LAASeR_Gate: TooManyQuestionException")
        except LimitsExceededException:
            print("---> LAASeR_Gate: LimitsExceededException")
        except Exception:
            print("---> LAASeR_Gate: Exception")
        finally:
            return candidate  # noqa: B012 -- intentional: always return best-so-far candidate
