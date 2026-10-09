# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR with Repair loop algorithm, plus a signature/arity-awareness nudge.

Identical to the champion LAASeR_Repair algorithm in every respect (same repair
loop, same format/entry-point/parsing-error recovery), except for one isolated
addition to the generation prompt: an explicit warning not to assume a
function's parameter list from prose alone when no function stub/signature is
shown, since some tasks conventionally need parameters never named in the
text (e.g. a redundant array-length argument alongside the array itself). This
targets a real, repeated failure pattern (two independent tasks observed in
Fase 1 failure analysis) where the model silently assumed a single-argument
signature and never asked, rather than a specific task.

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

# answer codes
READY_TO_CODE_KEY = "READY_TO_CODE"
QUESTION_KEY = "QUESTION"

READY_TO_CODE_TEMPLATE = """
Please find below a coding task.
Task:
`{prompt}`

Important: the function must be named exactly `{entry_point}` independently of the task text above.

Important: check whether the task text actually shows you the function's full signature (its
exact parameter names and count), e.g. a `def {entry_point}(...):` stub. If no such stub is
shown, do not assume the function only takes the arguments explicitly named in the prose --
some tasks conventionally need extra parameters that are never mentioned in the text (for
example, a redundant array-length parameter alongside the array itself). If you cannot be
confident of the exact parameter list from the text alone, that uncertainty is itself a concrete,
valid reason to ask a clarifying question about the function's exact parameters, rather than
guessing a signature.

Please review it and determine if you have everything to implement it,
and write READY_TO_CODE followed by ```python and ```

If it is impossible for you to implement it because the description lacks crucial details,
please ask a simple and concrete question to the user (QUESTION: ...)

Notice that you will be participating in a prompt clarification competition,
where the goal is to implement the correct python function.
Clarification questions are just needed on prompts that are inaccurate,
but unnecessary questions are penalized.
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


def _code_generation(
    env: ClarificationEnvironment, problem: dict[str, Any], clarifications: list[str]
) -> str:
    gen_prompt = problem["prompt"]
    entry_point = problem["entry_point"]
    if len(clarifications) > 0:
        gen_prompt += "Clarifications:\n"
        for c in clarifications:
            gen_prompt += c

    messages = [
        {
            "role": "user",
            "content": (
                READY_TO_CODE_TEMPLATE.replace("{prompt}", gen_prompt).replace(
                    "{entry_point}", entry_point
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
        gen_prompt += "Clarifications:\n"
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


def _is_solution_plausible(response: str, entry_point: str) -> (str, str):
    try:
        code = _validate_and_parse_evalplus_result(response)
    except ValueError as e:
        return FORMAT_ERROR, str(e)

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return PARSING_ERROR, str(e)

    if any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_point
        for node in ast.walk(tree)
    ):
        return PARSING_OK, _validate_and_parse_evalplus_result(response)
    else:
        return INVALID_ENTRYPOINT, _validate_and_parse_evalplus_result(response)


class LAASeR_Signature(ClarificationAlgorithmBase):
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        clarifications = []
        candidate = ""
        try:
            entry_point = problem["entry_point"]
            status = CODE_GEN
            response = ""
            while True:
                # check generation status
                if status == CODE_GEN:
                    response = _code_generation(env, problem, clarifications)
                elif status == FORMAT_ERROR:
                    response = _repair_format_error(env, response)
                elif status == INVALID_ENTRYPOINT:
                    response = _repair_invalid_entrypoint(env, problem, response)
                elif status == PARSING_ERROR:
                    response = _repair_parsing_error(env, problem, clarifications, response)
                else:  # status == PARSING_OK
                    return response

                # check llm response status
                if READY_TO_CODE_KEY in response:
                    status, _ = _is_solution_plausible(response, entry_point)
                    if status == PARSING_OK:
                        candidate = _validate_and_parse_evalplus_result(response)
                        return candidate

                elif QUESTION_KEY in response:
                    _, clarifying_question = response.split(QUESTION_KEY, 1)
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

        except TooManyQuestionException:
            print("---> LAASeR: TooManyQuestionException")
        except LimitsExceededException:
            print("---> LAASeR: LimitsExceededException")
        except Exception:
            # The response might not contain an answer, assume a question is raised.
            print("---> LAASeR: Exception")
        finally:
            return candidate  # noqa: B012 -- intentional: always return best-so-far candidate
