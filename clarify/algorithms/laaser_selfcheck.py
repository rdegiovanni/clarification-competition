# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR_SelfCheck: the champion's own low-ask decision logic, plus a self-check-and-repair step.

Fase 3 challenger #13 in the lineage (originally developed and measured under the working name
`laaser_gate_v9.py` / `LAASeR_GateV9`; renamed here because, unlike the `laaser_gate_v*.py`
lineage it grew out of, this file has no "gate" verification step at all -- the name had stopped
describing what the code does). It started as an isolation ablation of `laaser_gate_v8.py`
(`LAASeR_GateV8`): that file stacked two additions onto the champion's own low-ask decision logic
-- `laaser_concretequestion.py`'s "prefer a concrete example when you do ask" wording, and an
`EXAMPLES:`-writing self-check step -- and measured a clarification rate (21.11%) well above both
the champion's (5.00%) and `LAASeR_ConcreteQuestion`'s on its own (10.00%). This file isolates
which addition was responsible by keeping only the `EXAMPLES:`/self-check piece and reverting the
question wording to the champion's original plain phrasing.

Result: clarification rate dropped to 13.33% (down from 21.11%, but still above the champion's
5.00%) and TDS came out as the closest to the champion of any challenger measured in this entire
Fase 3 line (gap 0.0186, smaller than this variant's own run-to-run stdev) -- so the ablation
itself turned out to be the strongest candidate, not just a diagnostic. See `REPORT.md`'s
2026-10-12 `LAASeR_GateV9` entry for the full numbers (recorded under that name; this is the same
code, renamed afterward).

Team: LAASeR - LIST
Team Members: Matias Brizzio, Jordi Cabot, Renzo Degiovanni
Main Contact: main.contact@email.com
"""

from __future__ import annotations

import ast
import base64
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

# answer codes
READY_TO_CODE_KEY = "READY_TO_CODE"
QUESTION_KEY = "QUESTION"

MAX_SELFCHECK_REPAIRS = 2
_SELFCHECK_FALSE_RE = re.compile(r"SELFCHECK_(\d+)=False actual=(.*?) expected=")

READY_TO_CODE_TEMPLATE = """
Please find below a coding task.
Task:
`{prompt}`

Important: the function must be named exactly `{entry_point}` independently of the task text above.

Please review it and determine if you have everything to implement it.

If it is impossible for you to implement it because the description lacks crucial details,
please ask a simple and concrete question to the user (QUESTION: ...)

Otherwise, if you are ready to code: first write an "EXAMPLES:" section, a plain Python literal
list of 2-3 (arguments, expected_output) pairs that YOU believe your implementation must satisfy,
e.g. EXAMPLES: [((3.5,), 0.5), ((-2, 4), 2)] -- the first element of each pair is a tuple of the
arguments you would pass to `{entry_point}`, matching its exact parameter count, the second is
the exact value you expect it to return for them. If you cannot think of any concrete example,
write "EXAMPLES: none". Then write READY_TO_CODE followed by ```python and ```.

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

SELFCHECK_REPAIR_TEMPLATE = """
You stated that your implementation of `{entry_point}` should satisfy this example:
Call: `{entry_point}{args}`
Expected output: `{expected}`

But when your candidate below is actually run on that input, it returns: `{actual}`

```python
{code}
```

Please fix the implementation so it correctly satisfies this example (while still solving the
task). Write READY_TO_CODE followed by ```python and ``` with the corrected implementation.
""".strip()

SELFCHECK_SCRIPT_TEMPLATE = """
import base64


def _load(src_b64, name):
    try:
        src = base64.b64decode(src_b64).decode()
    except Exception as e:
        return None, "DECODE_ERROR:" + type(e).__name__
    ns = {}
    try:
        exec(src, ns)
    except Exception as e:
        return None, "LOAD_ERROR:" + type(e).__name__
    fn = ns.get(name)
    if fn is None:
        return None, "LOAD_ERROR:missing_function"
    return fn, None


fn, err = _load("{code_b64}", "{entry_point}")

examples = {examples_repr}

for i, (args, expected) in enumerate(examples):
    if err:
        actual = err
    else:
        try:
            actual = fn(*args)
        except Exception as e:
            actual = "ERROR:" + type(e).__name__
    print(
        "SELFCHECK_" + str(i) + "=" + str(actual == expected)
        + " actual=" + repr(actual) + " expected=" + repr(expected)
    )
""".strip()


def _code_generation(
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


def _self_check_repair(
    env: ClarificationEnvironment,
    entry_point: str,
    args: tuple,
    expected: Any,
    actual_text: str,
    code: str,
) -> str:
    messages = [
        {
            "role": "user",
            "content": (
                SELFCHECK_REPAIR_TEMPLATE.replace("{entry_point}", entry_point)
                .replace("{args}", repr(args))
                .replace("{expected}", repr(expected))
                .replace("{actual}", actual_text)
                .replace("{code}", code)
            ),
        }
    ]

    return READY_TO_CODE_KEY + "\n" + env.llm(messages)


def _is_solution_plausible(response: str, entry_point: str) -> tuple[str, Any]:
    try:
        code = _validate_and_parse_evalplus_result(response)
    except ValueError as e:
        return FORMAT_ERROR, str(e)

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return PARSING_ERROR, str(e)

    param_count = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_point:
            param_count = len(node.args.args)
            break

    if param_count is None:
        return INVALID_ENTRYPOINT, code

    examples: list[tuple[tuple, Any]] = []
    if "EXAMPLES:" in response:
        preamble = response.split("```python", 1)[0].replace(READY_TO_CODE_KEY, "").strip()
        _, _, examples_text = preamble.partition("EXAMPLES:")
        try:
            parsed = ast.literal_eval(examples_text.strip())
            if isinstance(parsed, list):
                for item in parsed:
                    if (
                        isinstance(item, tuple)
                        and len(item) == 2
                        and isinstance(item[0], tuple)
                        and len(item[0])
                        == param_count  # arg-count guard: fixes v7's corruption risk
                    ):
                        examples.append(item)
        except (ValueError, SyntaxError):
            pass

    return PARSING_OK, (code, examples)


def _build_selfcheck_script(entry_point: str, code: str, examples: list[tuple[tuple, Any]]) -> str:
    code_b64 = base64.b64encode(code.encode()).decode()
    return (
        SELFCHECK_SCRIPT_TEMPLATE.replace("{code_b64}", code_b64)
        .replace("{entry_point}", entry_point)
        .replace("{examples_repr}", repr(examples))
    )


def _self_check_and_repair(
    env: ClarificationEnvironment,
    entry_point: str,
    code: str,
    examples: list[tuple[tuple, Any]],
) -> str:
    if not examples:
        return code

    for attempt in range(MAX_SELFCHECK_REPAIRS + 1):
        probe_script = _build_selfcheck_script(entry_point, code, examples)
        probe_output = env.exec_code(probe_script)
        match = _SELFCHECK_FALSE_RE.search(probe_output)
        if match is None:
            return code
        if attempt == MAX_SELFCHECK_REPAIRS:
            return code  # give up: exhausted repair attempts, submit last candidate as-is

        idx = int(match.group(1))
        actual_text = match.group(2)
        args, expected = examples[idx]
        repair_response = _self_check_repair(env, entry_point, args, expected, actual_text, code)
        new_status, payload = _is_solution_plausible(repair_response, entry_point)
        if new_status == PARSING_OK:
            code, _ = payload
        else:
            return code  # malformed repair: give up with the last good candidate

    return code


class LAASeR_SelfCheck(ClarificationAlgorithmBase):
    def run(self, env: ClarificationEnvironment, problem: dict[str, Any]) -> str:
        clarifications: list[str] = []
        candidate = ""
        try:
            entry_point = problem["entry_point"]
            status = CODE_GEN
            response = ""
            while True:
                if status == CODE_GEN:
                    response = _code_generation(env, problem, clarifications)
                elif status == FORMAT_ERROR:
                    response = _repair_format_error(env, response)
                elif status == INVALID_ENTRYPOINT:
                    response = _repair_invalid_entrypoint(env, problem, response)
                elif status == PARSING_ERROR:
                    response = _repair_parsing_error(env, problem, clarifications, response)
                else:  # status == PARSING_OK
                    return candidate

                if READY_TO_CODE_KEY in response:
                    status, payload = _is_solution_plausible(response, entry_point)
                    if status == PARSING_OK:
                        code, examples = payload
                        candidate = code  # commit the valid draft before the riskier self-check
                        candidate = _self_check_and_repair(env, entry_point, candidate, examples)
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
            print("---> LAASeR_SelfCheck: TooManyQuestionException")
        except LimitsExceededException:
            print("---> LAASeR_SelfCheck: LimitsExceededException")
        except Exception:
            print("---> LAASeR_SelfCheck: Exception")
        finally:
            return candidate  # noqa: B012 -- intentional: always return best-so-far candidate
