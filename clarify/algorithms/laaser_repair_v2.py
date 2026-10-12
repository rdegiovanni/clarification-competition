# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR Repair v2: hardens the repair loop from LAASeR_Repair.

Same question/code-generation flow as LAASeR_Repair, with four fixes found by
tracing the original loop:
1. A cap on consecutive repair/regeneration attempts per code-generation round,
   so a response that never settles into a usable shape can't retry forever.
2. A fallback to the best syntactically-valid candidate seen so far (even one
   with the wrong function name) instead of returning "" once the cap is hit.
3. An explicit branch for a response that contains neither READY_TO_CODE nor a
   QUESTION marker, which previously left the state machine stuck.
4. A clear blank-line separator before "Clarifications:" in the regenerated
   prompt, instead of gluing it directly onto the end of the task text.

We make the LLM aware that its output will be part of a competition.
We explain to it that the main goal is to implement the correct function,
but unnecessary questions are penalized.


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

# generation codes
CODE_GEN = "CODE_GEN"
FORMAT_ERROR = "IncorrectOutputFormat"
PARSING_ERROR = "SyntaxError"
PARSING_OK = "CorrectSyntax"
INVALID_ENTRYPOINT = "InvalidEntryPoint"
NO_KEYWORD = "NoKeyword"

# answer codes
READY_TO_CODE_KEY = "READY_TO_CODE"
QUESTION_KEY = "QUESTION"
QUESTION_PATTERN = re.compile(r"QUESTION\s*:")

# Cap on consecutive repair/regeneration attempts within one code-generation
# round (reset whenever a fresh clarification answer restarts generation).
MAX_REPAIR_ATTEMPTS = 3

READY_TO_CODE_TEMPLATE = """
Please find below a coding task.
Task:
`{prompt}`

Important: the function must be named exactly `{entry_point}` independently of the task text above.

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

REPAIR_NO_KEYWORD_TEMPLATE = """
Your previous response did not contain a valid answer: it had no READY_TO_CODE marker
with a ```python and ``` block, and no QUESTION: clarifying question.

Response:
`{response}`

Please respond with exactly one of the two:
- READY_TO_CODE followed by a ```python and ``` block with the complete function, or
- QUESTION: a single concrete question
""".strip()


def _code_generation(
    env: ClarificationEnvironment, problem: dict[str, Any], clarifications: list[str]
) -> str:
    gen_prompt = problem["prompt"]
    entry_point = problem["entry_point"]
    if clarifications:
        gen_prompt += "\n\nClarifications:\n" + "\n".join(clarifications)

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
    env: ClarificationEnvironment,
    problem: dict[str, Any],
    clarifications: list[str],
    response: str,
) -> str:
    gen_prompt = problem["prompt"]
    entry_point = problem["entry_point"]
    if clarifications:
        gen_prompt += "\n\nClarifications:\n" + "\n".join(clarifications)

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


def _repair_no_keyword(env: ClarificationEnvironment, response: str) -> str:
    messages = [
        {
            "role": "user",
            "content": (REPAIR_NO_KEYWORD_TEMPLATE.replace("{response}", response)),
        }
    ]

    return env.llm(messages)


def _looks_like_code(response: str) -> bool:
    return "```python" in response or READY_TO_CODE_KEY in response


def _is_solution_plausible(response: str, entry_point: str) -> tuple[str, str]:
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
        return PARSING_OK, code
    else:
        return INVALID_ENTRYPOINT, code


class LAASeR_RepairV2(ClarificationAlgorithmBase):
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        clarifications: list[str] = []
        candidate = ""
        best_parseable_code = ""
        try:
            entry_point = problem["entry_point"]
            status = CODE_GEN
            response = ""
            repair_attempts = 0
            while True:
                if status == CODE_GEN:
                    response = _code_generation(env, problem, clarifications)
                    repair_attempts = 0
                elif status == FORMAT_ERROR:
                    repair_attempts += 1
                    response = _repair_format_error(env, response)
                elif status == INVALID_ENTRYPOINT:
                    repair_attempts += 1
                    response = _repair_invalid_entrypoint(env, problem, response)
                elif status == PARSING_ERROR:
                    repair_attempts += 1
                    response = _repair_parsing_error(env, problem, clarifications, response)
                else:  # status == NO_KEYWORD
                    repair_attempts += 1
                    response = _repair_no_keyword(env, response)

                if repair_attempts > MAX_REPAIR_ATTEMPTS:
                    break

                if _looks_like_code(response):
                    status, msg = _is_solution_plausible(response, entry_point)
                    if status == PARSING_OK:
                        candidate = msg
                        return candidate
                    if status == INVALID_ENTRYPOINT:
                        best_parseable_code = msg
                elif QUESTION_PATTERN.search(response):
                    _, clarifying_question = QUESTION_PATTERN.split(response, 1)
                    clarification = env.ask_human(clarifying_question)
                    num_rounds = len(clarifications)
                    clarifications.append(
                        f"Question #{num_rounds + 1}: {clarifying_question.strip()}\n"
                        f"Answer: {clarification.strip()}"
                    )
                    status = CODE_GEN
                else:
                    status = NO_KEYWORD

        except TooManyQuestionException:
            print("---> LAASeR_RepairV2: TooManyQuestionException")
        except LimitsExceededException:
            print("---> LAASeR_RepairV2: LimitsExceededException")
        except Exception:
            # The response might not contain an answer, assume a question is raised.
            print("---> LAASeR_RepairV2: Exception")
        return candidate or best_parseable_code
