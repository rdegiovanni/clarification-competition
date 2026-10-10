# SPDX-FileCopyrightText: 2026 Submitter <submitter@email.com>
#
# SPDX-License-Identifier: Open Source License like MIT, Apache 2.0, ...

"""Algorithm name.

LAASeR with a draft-first gate, verified by execution (not self-judgment).

Fase 3 challenger #6. `LAASeR_Gate` (challenger #5) confirmed that an atomic, concrete,
single-fact clarifying question scores far better with the simulated human than an
abstract or bundled one (nDCG 0.9889 vs. the champion's 0.0333 across 3 runs) -- but its
GATE step, which decided whether to ask purely from the model's own self-report of
"this assumption might be critical", said DONE almost never (100% clarification rate in
all 3 runs), asking even on tasks the champion already solved without a question.

This version keeps the validated question style but replaces the self-judged gate with
an execution-grounded check, in the spirit of the "behavior-changing questions" idea from
recent clarification-benchmark literature (e.g. arXiv:2610.01769, "Discovering and
Qualifying Behavior-Changing Questions for Selective Clarification in LLM Code
Generation"): rather than trust the model's claim that an assumption is critical, generate
an alternative candidate reflecting the opposite choice for that one assumption, and
actually run both candidates (via env.exec_code) on a few concrete inputs the model itself
proposes. Only if the two candidates' outputs genuinely diverge on at least one input is
the (already-drafted, already atomic) question actually asked; otherwise the draft
candidate is returned as-is, even if the model's own response claimed the assumption was
critical. Reuses the champion's format/entry-point/parsing-error repair handlers
unchanged -- not part of this hypothesis.

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
ALT_PROBE = "ALT_PROBE"

# answer codes
READY_TO_CODE_KEY = "READY_TO_CODE"

MAX_DRAFT_ATTEMPTS = 8
_DIVERGE_TRUE_RE = re.compile(r"DIVERGE_\d+=True")

DRAFT_TEMPLATE = """
Please find below a coding task.
Task:
`{prompt}`

Important: the function must be named exactly `{entry_point}` independently of the task text above.

First, write a short "ASSUMPTIONS:" section (plain bullet points) listing anything you had to
infer that is NOT explicitly stated in the task text above -- in particular: whether there might
be a parameter the task text never names (a common convention for array/list functions is a
redundant length argument alongside the array itself), any edge case, sign, range, or type you
assumed, and any default or tie-break behavior you chose. If there is truly nothing you had to
infer, write "ASSUMPTIONS: none".

Then write READY_TO_CODE followed by ```python and ``` containing your best implementation.

Notice that you will be participating in a prompt clarification competition, where the goal is to
implement the correct python function, but unnecessary clarification turns are penalized -- so
write your best candidate directly here. You will get a separate chance to ask a question only if
one of your own listed assumptions turns out to be genuinely critical.
""".strip()

ALT_PROBE_TEMPLATE = """
You drafted the candidate implementation below for a coding task, along with a list of
assumptions you made because the task text did not state them explicitly.

Candidate:
```python
{candidate}
```

Your stated assumptions:
`{assumptions}`

Pick AT MOST ONE assumption above that you are genuinely unsure about. If none of your
assumptions would change whether the candidate is correct, or you listed no assumptions, write
exactly DONE and nothing else.

Otherwise, write all four of the following, in this exact order:

ASSUMPTION: <restate the one assumption you picked>
ALTERNATIVE:
```python
<a full alternative implementation of the SAME function that makes the OPPOSITE or a materially
different choice for that one assumption, keeping everything else the same>
```
INPUTS: <a plain Python literal list of argument tuples that would be passed to `{entry_point}`
exactly as you defined it in your candidate above, e.g. [(1, 2), (3, -1)] -- choose inputs you
believe would make your candidate and the alternative above disagree>
QUESTION: <exactly ONE atomic, concrete, closed-form question that confirms or denies a SINGLE
specific fact about a SINGLE specific input -- not an abstract or open-ended question, not more
than one sub-question, and never asking the user to write code or reveal test cases>
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

PROBE_SCRIPT_TEMPLATE = """
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


fn_a, err_a = _load("{orig_b64}", "{entry_point}")
fn_b, err_b = _load("{alt_b64}", "{entry_point}")

inputs = {inputs_repr}

for i, args in enumerate(inputs):
    if err_a:
        ra = err_a
    else:
        try:
            ra = fn_a(*args)
        except Exception as e:
            ra = "ERROR:" + type(e).__name__
    if err_b:
        rb = err_b
    else:
        try:
            rb = fn_b(*args)
        except Exception as e:
            rb = "ERROR:" + type(e).__name__
    print("DIVERGE_" + str(i) + "=" + str(ra != rb) + " A=" + repr(ra) + " B=" + repr(rb))
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


def _alt_probe(
    env: ClarificationEnvironment, candidate: str, assumptions: str, entry_point: str
) -> str:
    messages = [
        {
            "role": "user",
            "content": (
                ALT_PROBE_TEMPLATE.replace("{candidate}", candidate)
                .replace("{assumptions}", assumptions or "none")
                .replace("{entry_point}", entry_point)
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


def _parse_alt_probe(response: str) -> tuple[str, list, str] | None:
    if "ALTERNATIVE:" not in response or "INPUTS:" not in response or "QUESTION:" not in response:
        return None

    try:
        alt_code = _validate_and_parse_evalplus_result(response)
    except ValueError:
        return None

    try:
        _, after_inputs = response.split("INPUTS:", 1)
        inputs_text, _, question_text = after_inputs.partition("QUESTION:")
        inputs = ast.literal_eval(inputs_text.strip())
    except (ValueError, SyntaxError):
        return None

    if not isinstance(inputs, list) or len(inputs) == 0:
        return None
    if not all(isinstance(args, tuple) for args in inputs):
        return None

    question = question_text.strip()
    if not question:
        return None

    return alt_code, inputs, question


def _build_probe_script(entry_point: str, original_code: str, alt_code: str, inputs: list) -> str:
    orig_b64 = base64.b64encode(original_code.encode()).decode()
    alt_b64 = base64.b64encode(alt_code.encode()).decode()
    return (
        PROBE_SCRIPT_TEMPLATE.replace("{orig_b64}", orig_b64)
        .replace("{alt_b64}", alt_b64)
        .replace("{entry_point}", entry_point)
        .replace("{inputs_repr}", repr(inputs))
    )


class LAASeR_GateV2(ClarificationAlgorithmBase):
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
                if status == ALT_PROBE:
                    alt_response = _alt_probe(env, candidate, assumptions, entry_point)
                    parsed = _parse_alt_probe(alt_response)
                    if parsed is None:
                        return candidate  # DONE, or malformed: fail safe, never ask

                    alt_code, inputs, question = parsed
                    probe_script = _build_probe_script(entry_point, candidate, alt_code, inputs)
                    probe_output = env.exec_code(probe_script)

                    if _DIVERGE_TRUE_RE.search(probe_output):
                        clarification = env.ask_human(question)
                        num_rounds = len(clarifications)
                        clarifications += [
                            f"Question #{num_rounds + 1}:\n{question}\nAnswer:\n{clarification}\n"
                        ]
                        status = CODE_GEN
                        continue
                    else:
                        return candidate  # no confirmed behavioral difference: never ask

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
                        status = ALT_PROBE
                    else:
                        status = new_status
                else:
                    status = FORMAT_ERROR

        except TooManyQuestionException:
            print("---> LAASeR_GateV2: TooManyQuestionException")
        except LimitsExceededException:
            print("---> LAASeR_GateV2: LimitsExceededException")
        except Exception:
            print("---> LAASeR_GateV2: Exception")
        finally:
            return candidate  # noqa: B012 -- intentional: always return best-so-far candidate
